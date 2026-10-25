"""Speak: prepare the text, reuse a stored file or synthesize one, store it."""

from __future__ import annotations

import asyncio
from typing import Protocol

from src.config import Settings
from src.contract import DeleteResult, DownloadableVoices, DownloadResult, SpeakResult, VoiceEntry, VoiceList
from src.engine import TtsEngine
from src.errors import AdminRequired, DeleteFailed, IdentityRequired, VoiceUnavailable
from src.store import AudioStore
from src.text_prep import prepare

_NO_IDENTITY = "No signed-in user was sent with this request."


class VoiceSource(Protocol):
    async def list(self, language: str | None, quality: str | None) -> list[VoiceEntry]: ...

    async def install(self, name: str) -> VoiceEntry: ...

    async def remove(self, name: str) -> None: ...


class AdminCheck(Protocol):
    async def is_admin(self, username: str) -> bool: ...


class BardService:
    def __init__(
        self,
        engine: TtsEngine,
        store: AudioStore,
        settings: Settings,
        library: VoiceSource,
        gate: AdminCheck,
        delete_gate: AdminCheck,
    ) -> None:
        self._engine = engine
        self._store = store
        self._settings = settings
        self._library = library
        self._gate = gate
        self._delete_gate = delete_gate  # asks for bard.delete, which bard.admin does not imply
        self._slots = asyncio.Semaphore(settings.max_concurrent)
        # shortcut: a lock may be dropped while a waiter still holds it, so two identical
        # requests can then both synthesize; harmless (same file id), upgrade if it ever hurts.
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def list_voices(self) -> VoiceList:
        voices = await asyncio.to_thread(self._engine.voices)
        return VoiceList(
            voices=voices,
            default=self._settings.voice,
            message=f"{len(voices)} voice(s) installed; the default is {self._settings.voice}.",
        )

    async def _require_admin(self, owner: str) -> None:
        if not owner:
            raise IdentityRequired(_NO_IDENTITY)
        if not await self._gate.is_admin(owner):
            raise AdminRequired("Only Bard admins can do this. Ask an administrator for the bard.admin permission.")

    async def list_downloadable(self, owner: str, language: str | None, quality: str | None) -> DownloadableVoices:
        await self._require_admin(owner)
        voices = await self._library.list(language, quality)
        have = sum(v.installed for v in voices)
        return DownloadableVoices(
            voices=voices,
            message=f"{len(voices)} voice(s) match; {have} already installed. Install one with tool_bard_downloadVoice.",
        )

    async def download_voice(self, owner: str, name: str) -> DownloadResult:
        await self._require_admin(owner)
        voice = await self._library.install(name)
        return DownloadResult(
            voice=voice.voice,
            size_mb=voice.size_mb,
            message=f'Installed {voice.voice} ({voice.size_mb} MB). Pass voice="{voice.voice}" to tool_bard_speak to use it.',
        )

    async def delete_voice(self, owner: str, name: str) -> DeleteResult:
        if not owner:
            raise IdentityRequired(_NO_IDENTITY)
        if not await self._delete_gate.is_admin(owner):
            raise AdminRequired("Only users with the bard.delete permission can delete voices. Ask an administrator for it.")
        if name == self._settings.voice:
            raise DeleteFailed(f"{name} is the default voice and cannot be deleted. Change BARD_VOICE first.")
        # Unload first: a loaded model can keep its file open, which blocks the delete on Windows.
        await asyncio.to_thread(self._engine.unload, name)
        await self._library.remove(name)
        return DeleteResult(voice=name, message=f"Deleted {name}. It can be downloaded again with tool_bard_downloadVoice.")

    async def speak(self, owner: str, text: str, voice: str | None = None) -> SpeakResult:
        if not owner:
            raise IdentityRequired(_NO_IDENTITY)
        voice = voice or self._settings.voice
        if voice not in await asyncio.to_thread(self._engine.voices):
            raise VoiceUnavailable(f"Voice '{voice}' is not installed. Call tool_bard_listVoices for the list.")
        clean = prepare(text, self._settings.max_chars)
        file_id = AudioStore.file_id(voice, clean)
        key = (owner, file_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                stored = await asyncio.to_thread(self._store.get, owner, file_id)
                cached = stored is not None
                if stored is None:
                    async with self._slots:
                        synthesis = await self._engine.synthesize(clean, voice)
                    stored = await asyncio.to_thread(
                        self._store.put, owner, file_id, synthesis.mp3, voice, synthesis.duration_s
                    )
        finally:
            if self._locks.get(key) is lock and not lock.locked():
                del self._locks[key]
        note = ", from cache" if cached else ""
        return SpeakResult(
            file_id=file_id,
            voice=voice,
            duration_s=stored.duration_s,
            size_bytes=stored.size_bytes,
            cached=cached,
            message=f"Speech ready ({stored.duration_s:.1f} s, voice {voice}{note}). The player is shown in the chat.",
        )
