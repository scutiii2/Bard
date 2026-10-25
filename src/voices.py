"""The Piper voice catalog and a staged, verified installer.

A voice is downloaded into a staging folder, checked against the catalog's size and MD5,
and only then moved into the voices folder, so a failed download never leaves a half-written
voice that Bard would list as installed."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from src.contract import VoiceEntry
from src.errors import CatalogUnavailable, DeleteFailed, DownloadFailed, VoiceAlreadyInstalled, VoiceNotInCatalog, VoiceUnavailable

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
DEFAULT_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_CHUNK = 1 << 20
_MB = 1 << 20


@dataclass(frozen=True)
class _Voice:
    key: str
    language: str
    quality: str
    files: dict[str, tuple[str, int, str]]  # local suffix -> (remote path, size, md5)

    @property
    def size_bytes(self) -> int:
        return sum(size for _, size, _ in self.files.values())


def _parse(raw: object) -> dict[str, _Voice]:
    if not isinstance(raw, dict):
        raise CatalogUnavailable("The voice catalog had an unexpected format.")
    voices: dict[str, _Voice] = {}
    for key, meta in raw.items():
        try:
            if not _NAME.match(key):
                continue
            files = {
                suffix: (path, int(info["size_bytes"]), str(info["md5_digest"]))
                for path, info in meta["files"].items()
                for suffix in (".onnx", ".onnx.json")
                if path.endswith(f"{key}{suffix}")
            }
            if set(files) == {".onnx", ".onnx.json"}:
                voices[key] = _Voice(key, str(meta["language"]["code"]), str(meta["quality"]), files)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return voices


class VoiceLibrary:
    def __init__(
        self,
        client: httpx.AsyncClient,
        voices_dir: Path,
        staging_dir: Path,
        catalog_url: str = DEFAULT_CATALOG_URL,
        base_url: str = DEFAULT_BASE_URL,
        max_bytes: int = 400 * _MB,
        catalog_ttl_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._voices_dir = Path(voices_dir)
        self._staging = Path(staging_dir)
        self._catalog_url = catalog_url
        self._base_url = base_url
        self._max_bytes = max_bytes
        self._catalog_ttl = catalog_ttl_seconds
        self._clock = clock
        self._catalog: dict[str, _Voice] | None = None
        self._fetched_at = 0.0
        self._catalog_lock = asyncio.Lock()
        self._install_lock = asyncio.Lock()

    async def _voices(self) -> dict[str, _Voice]:
        async with self._catalog_lock:
            if self._catalog is not None and self._clock() - self._fetched_at < self._catalog_ttl:
                return self._catalog
            try:
                response = await self._client.get(self._catalog_url, timeout=30)
                response.raise_for_status()
                catalog = _parse(response.json())
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("voice catalog unavailable: %s", type(error).__name__)
                raise CatalogUnavailable("The voice catalog could not be fetched. Try again later.") from error
            self._catalog, self._fetched_at = catalog, self._clock()
            return catalog

    def _installed(self) -> set[str]:
        if not self._voices_dir.is_dir():
            return set()
        return {p.name.removesuffix(".onnx") for p in self._voices_dir.glob("*.onnx")}

    @staticmethod
    def _entry(voice: _Voice, installed: bool) -> VoiceEntry:
        return VoiceEntry(
            voice=voice.key, language=voice.language, quality=voice.quality,
            size_mb=round(voice.size_bytes / _MB, 1), installed=installed,
        )

    async def list(self, language: str | None, quality: str | None) -> list[VoiceEntry]:
        voices = await self._voices()
        installed = await asyncio.to_thread(self._installed)
        wanted_language = language.strip().lower() if language else ""
        wanted_quality = quality.strip().lower() if quality else ""
        entries = []
        for key in sorted(voices):
            voice = voices[key]
            code = voice.language.lower()
            if wanted_language and code != wanted_language and not code.startswith(wanted_language + "_"):
                continue
            if wanted_quality and voice.quality.lower() != wanted_quality:
                continue
            entries.append(self._entry(voice, key in installed))
        return entries

    async def install(self, name: str) -> VoiceEntry:
        voices = await self._voices()
        voice = voices.get(name) if _NAME.match(name or "") else None
        if voice is None:
            raise VoiceNotInCatalog("That name is not in the voice catalog. Use tool_bard_listDownloadable for valid names.")
        if voice.size_bytes > self._max_bytes:
            raise DownloadFailed(
                f"{voice.key} is {voice.size_bytes / _MB:.0f} MB, over the {self._max_bytes // _MB} MB limit."
            )
        async with self._install_lock:
            if voice.key in await asyncio.to_thread(self._installed):
                raise VoiceAlreadyInstalled(f"{voice.key} is already installed.")
            await asyncio.to_thread(self._check_disk, voice.size_bytes)
            stage = await asyncio.to_thread(self._make_stage)
            try:
                for suffix, (path, size, digest) in voice.files.items():
                    await self._fetch(self._base_url + path, stage / f"{voice.key}{suffix}", size, digest)
                await asyncio.to_thread(self._publish, stage, voice.key)
            finally:
                await asyncio.to_thread(shutil.rmtree, stage, True)
        logger.info("installed voice %s", voice.key)
        return self._entry(voice, True)

    async def remove(self, name: str) -> None:
        async with self._install_lock:
            if not _NAME.match(name or "") or name not in await asyncio.to_thread(self._installed):
                raise VoiceUnavailable(f"Voice '{name}' is not installed. Call tool_bard_listVoices for the list.")
            try:
                await asyncio.to_thread(self._unlink, name)
            except OSError as error:
                logger.warning("voice delete failed: %s", type(error).__name__)
                raise DeleteFailed("The voice files could not be deleted; it may be in use. Try again later.") from error
        logger.info("deleted voice %s", name)

    def _unlink(self, key: str) -> None:
        # The .onnx first: Bard lists a voice by its .onnx, so a half-deleted voice is never listed.
        (self._voices_dir / f"{key}.onnx").unlink()
        (self._voices_dir / f"{key}.onnx.json").unlink(missing_ok=True)

    def _check_disk(self, size: int) -> None:
        self._voices_dir.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self._voices_dir).free < 2 * size:
            raise DownloadFailed("There is not enough free disk space on the Bard host for this voice.")

    def _make_stage(self) -> Path:
        self._staging.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(dir=self._staging))

    def _publish(self, stage: Path, key: str) -> None:
        # The config first: Bard lists a voice by its .onnx, so a listed voice always has its config.
        os.replace(stage / f"{key}.onnx.json", self._voices_dir / f"{key}.onnx.json")
        os.replace(stage / f"{key}.onnx", self._voices_dir / f"{key}.onnx")

    @staticmethod
    def _write(out, digest, chunk: bytes) -> None:
        out.write(chunk)
        digest.update(chunk)

    async def _fetch(self, url: str, target: Path, size: int, md5: str) -> None:
        digest = hashlib.md5()
        written = 0
        out = await asyncio.to_thread(open, target, "wb")
        try:
            async with self._client.stream("GET", url, timeout=httpx.Timeout(30, read=120)) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(_CHUNK):
                    written += len(chunk)
                    if written > size:
                        raise DownloadFailed("A download was larger than the catalog says (size mismatch).")
                    await asyncio.to_thread(self._write, out, digest, chunk)
        except httpx.HTTPError as error:
            logger.warning("voice download failed: %s", type(error).__name__)
            raise DownloadFailed("The download failed; check the Bard host's connection to the voice server.") from error
        finally:
            await asyncio.to_thread(out.close)
        if written != size:
            raise DownloadFailed("A download was incomplete (size mismatch).")
        if digest.hexdigest() != md5:
            raise DownloadFailed("A download failed its checksum.")
