import io
import shutil
import wave
from pathlib import Path

import pytest

from src.engine import PiperEngine
from src.errors import EngineFailed, VoiceUnavailable

VOICES = Path(__file__).resolve().parent.parent / ".data" / "voices"
NEEDS_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def silent_wav(seconds: float = 0.5, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def test_voices_lists_onnx_stems_only(tmp_path):
    (tmp_path / "en_US-a.onnx").write_bytes(b"")
    (tmp_path / "en_US-a.onnx.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("")
    assert PiperEngine(tmp_path).voices() == ["en_US-a"]


def test_voices_is_empty_when_the_directory_is_missing(tmp_path):
    assert PiperEngine(tmp_path / "nope").voices() == []


async def test_unknown_voice_is_voice_unavailable(tmp_path):
    with pytest.raises(VoiceUnavailable):
        await PiperEngine(tmp_path).synthesize("hi", "missing")


async def test_missing_ffmpeg_is_engine_failed(tmp_path):
    with pytest.raises(EngineFailed, match="ffmpeg"):
        await PiperEngine(tmp_path, ffmpeg="definitely-not-ffmpeg")._mp3(silent_wav())


@NEEDS_FFMPEG
async def test_mp3_encoding_returns_mp3_bytes(tmp_path):
    mp3 = await PiperEngine(tmp_path)._mp3(silent_wav())
    assert mp3[:3] == b"ID3" or mp3[0] == 0xFF
    assert len(mp3) > 100


@NEEDS_FFMPEG
@pytest.mark.skipif(not (VOICES / "en_US-lessac-medium.onnx").exists(), reason="voice not downloaded")
async def test_real_synthesis_produces_speech():
    result = await PiperEngine(VOICES).synthesize("Hello from Bard.", "en_US-lessac-medium")
    assert result.duration_s > 0.5
    assert len(result.mp3) > 3000
