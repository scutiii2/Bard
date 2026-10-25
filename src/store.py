"""Per-owner MP3 files with a JSON sidecar, a time-to-live and a quota.

Blocking by design (plain file IO); the service calls it through asyncio.to_thread.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.errors import QuotaExceeded

_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class StoredAudio:
    file_id: str
    path: Path
    voice: str
    duration_s: float
    size_bytes: int
    created_at: float


class AudioStore:
    def __init__(
        self,
        root: Path,
        ttl_seconds: int,
        quota_bytes: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root)
        self._ttl = ttl_seconds
        self._quota = quota_bytes
        self._clock = clock

    @staticmethod
    def file_id(voice: str, text: str) -> str:
        return hashlib.sha256(f"{voice}\0{text}".encode("utf-8")).hexdigest()[:32]

    def _owner_dir(self, owner: str) -> Path:
        return self._root / hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16]

    def _expired(self, stored: StoredAudio) -> bool:
        return stored.created_at + self._ttl <= self._clock()

    @staticmethod
    def _read(owner_dir: Path, file_id: str) -> StoredAudio | None:
        mp3 = owner_dir / f"{file_id}.mp3"
        try:
            info = json.loads((owner_dir / f"{file_id}.json").read_text(encoding="utf-8"))
            return StoredAudio(
                file_id, mp3, info["voice"], float(info["duration_s"]), mp3.stat().st_size, float(info["created_at"])
            )
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _remove(owner_dir: Path, file_id: str) -> None:
        for suffix in (".mp3", ".json"):
            (owner_dir / f"{file_id}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get(self, owner: str, file_id: str) -> StoredAudio | None:
        if not _ID.match(file_id):
            return None
        owner_dir = self._owner_dir(owner)
        stored = self._read(owner_dir, file_id)
        if stored is None:
            return None
        if self._expired(stored):
            self._remove(owner_dir, file_id)
            return None
        return stored

    def _sweep_dir(self, owner_dir: Path) -> int:
        removed = 0
        for sidecar in owner_dir.glob("*.json"):
            stored = self._read(owner_dir, sidecar.stem)
            if stored is None or self._expired(stored):
                self._remove(owner_dir, sidecar.stem)
                removed += 1
        return removed

    def sweep(self) -> int:
        if not self._root.exists():
            return 0
        return sum(self._sweep_dir(d) for d in self._root.iterdir() if d.is_dir())

    def put(self, owner: str, file_id: str, mp3: bytes, voice: str, duration_s: float) -> StoredAudio:
        owner_dir = self._owner_dir(owner)
        owner_dir.mkdir(parents=True, exist_ok=True)
        self._sweep_dir(owner_dir)
        used = sum(p.stat().st_size for p in owner_dir.glob("*.mp3"))
        if used + len(mp3) > self._quota:
            raise QuotaExceeded("Your audio storage is full. Wait for older audio to expire and try again.")
        created = self._clock()
        meta = {"voice": voice, "duration_s": duration_s, "created_at": created}
        self._write(owner_dir / f"{file_id}.json", json.dumps(meta).encode("utf-8"))
        self._write(owner_dir / f"{file_id}.mp3", mp3)
        return StoredAudio(file_id, owner_dir / f"{file_id}.mp3", voice, duration_s, len(mp3), created)
