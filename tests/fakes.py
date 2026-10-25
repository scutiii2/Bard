import asyncio

from src.contract import VoiceEntry
from src.engine import Synthesis
from src.errors import VoiceNotInCatalog


class FakeEngine:
    """Stands in for Piper and ffmpeg: the 'mp3' is the text behind a prefix."""

    def __init__(self, voices: tuple[str, ...] = ("v1", "v2")) -> None:
        self._voices = list(voices)
        self.calls: list[tuple[str, str]] = []
        self.unloaded: list[str] = []

    def voices(self) -> list[str]:
        return list(self._voices)

    def unload(self, name: str) -> None:
        self.unloaded.append(name)

    async def synthesize(self, text: str, voice: str) -> Synthesis:
        self.calls.append((text, voice))
        await asyncio.sleep(0.01)
        return Synthesis(b"mp3:" + text.encode("utf-8"), 2.0)


class FakeGate:
    """Stands in for the ember_api permission check."""

    def __init__(self, admins: tuple[str, ...] = ()) -> None:
        self.admins = set(admins)
        self.asked: list[str] = []

    async def is_admin(self, username: str) -> bool:
        self.asked.append(username)
        return username in self.admins


class FakeLibrary:
    """Stands in for the Piper voice catalog and installer."""

    def __init__(self) -> None:
        self.entries = [
            VoiceEntry(voice="en_US-ryan-high", language="en_US", quality="high", size_mb=114.2, installed=False),
            VoiceEntry(voice="en_GB-alba-medium", language="en_GB", quality="medium", size_mb=63.5, installed=True),
        ]
        self.listed: list[tuple[str | None, str | None]] = []
        self.installed: list[str] = []
        self.removed: list[str] = []

    async def remove(self, name: str) -> None:
        self.removed.append(name)

    async def list(self, language: str | None, quality: str | None) -> list[VoiceEntry]:
        self.listed.append((language, quality))
        return list(self.entries)

    async def install(self, name: str) -> VoiceEntry:
        entry = next((e for e in self.entries if e.voice == name), None)
        if entry is None:
            raise VoiceNotInCatalog(f"'{name}' is not in the voice catalog.")
        self.installed.append(name)
        return entry.model_copy(update={"installed": True})
