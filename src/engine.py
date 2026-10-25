"""Text to MP3. Piper is CPU-bound and blocking, so it runs on a worker thread;
ffmpeg runs as an asyncio subprocess."""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.errors import EngineFailed, VoiceUnavailable


@dataclass(frozen=True)
class Synthesis:
    mp3: bytes
    duration_s: float


class TtsEngine(Protocol):
    def voices(self) -> list[str]: ...

    async def synthesize(self, text: str, voice: str) -> Synthesis: ...


class PiperEngine:
    def __init__(self, voices_dir: Path, ffmpeg: str = "ffmpeg") -> None:
        self._dir = Path(voices_dir)
        self._ffmpeg = ffmpeg
        self._loaded: dict[str, object] = {}
        self._load_lock = threading.Lock()

    def voices(self) -> list[str]:
        return sorted(p.name.removesuffix(".onnx") for p in self._dir.glob("*.onnx")) if self._dir.is_dir() else []

    def _voice(self, name: str):
        with self._load_lock:
            if name not in self._loaded:
                path = self._dir / f"{name}.onnx"
                if not path.is_file():
                    raise VoiceUnavailable(f"Voice '{name}' is not installed.")
                from piper import PiperVoice  # heavy import, only when a voice is first used

                self._loaded[name] = PiperVoice.load(path)
            return self._loaded[name]

    def _wav(self, text: str, name: str) -> tuple[bytes, float]:
        voice = self._voice(name)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            voice.synthesize_wav(text, wav)
            seconds = wav.getnframes() / wav.getframerate()
        return buf.getvalue(), seconds

    async def _mp3(self, wav: bytes) -> bytes:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._ffmpeg, "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
                "-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3", "pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise EngineFailed("ffmpeg was not found on the Bard host.") from error
        out, err = await proc.communicate(wav)
        if proc.returncode != 0:
            raise EngineFailed(f"ffmpeg could not encode the audio: {err.decode('utf-8', 'replace').strip()[:200]}")
        return out

    async def synthesize(self, text: str, voice: str) -> Synthesis:
        wav, seconds = await asyncio.to_thread(self._wav, text, voice)
        return Synthesis(await self._mp3(wav), seconds)
