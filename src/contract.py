"""Result models. `message` comes last: ember shows it first."""

from __future__ import annotations

from pydantic import BaseModel


class SpeakResult(BaseModel):
    file_id: str
    voice: str
    duration_s: float
    size_bytes: int
    cached: bool
    message: str


class VoiceList(BaseModel):
    voices: list[str]
    default: str
    message: str


class VoiceEntry(BaseModel):
    voice: str
    language: str
    quality: str
    size_mb: float
    installed: bool


class DownloadableVoices(BaseModel):
    voices: list[VoiceEntry]
    message: str


class DownloadResult(BaseModel):
    voice: str
    size_mb: float
    message: str


class DeleteResult(BaseModel):
    voice: str
    message: str
