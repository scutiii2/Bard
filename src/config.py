"""Bard settings, read from the environment (and a local .env, never committed)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8090
    internal_token: str = ""
    data_dir: Path = PROJECT_DIR / ".data"
    voice: str = "en_US-lessac-medium"
    ffmpeg: str = "ffmpeg"
    max_chars: int = 5000
    ttl_seconds: int = 24 * 3600
    quota_bytes: int = 200 * 1024 * 1024
    max_concurrent: int = 1
    # ember_api answers "does this username hold bard.admin"; BARD_ADMINS adds usernames
    # (lowercase) that count as admins even when ember_api cannot be reached.
    ember_api_url: str = "http://127.0.0.1:8030"
    admins: frozenset[str] = frozenset()

    @property
    def voices_dir(self) -> Path:
        return self.data_dir / "voices"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def exposed_without_token(self) -> bool:
        """Listening beyond loopback with no token lets anything that can reach the port call every tool."""
        return not self.internal_token and self.host not in LOOPBACK_HOSTS


def load_settings() -> Settings:
    load_dotenv(PROJECT_DIR / ".env")
    env = os.environ.get
    return Settings(
        host=env("BARD_HOST", "127.0.0.1"),
        port=int(env("BARD_PORT", "8090")),
        internal_token=env("INTERNAL_API_TOKEN", ""),
        data_dir=Path(env("BARD_DATA_DIR") or PROJECT_DIR / ".data"),
        voice=env("BARD_VOICE", "en_US-lessac-medium"),
        ffmpeg=env("BARD_FFMPEG", "ffmpeg"),
        max_chars=int(env("BARD_MAX_CHARS", "5000")),
        ttl_seconds=int(env("BARD_TTL_HOURS", "24")) * 3600,
        quota_bytes=int(env("BARD_QUOTA_MB", "200")) * 1024 * 1024,
        max_concurrent=int(env("BARD_MAX_CONCURRENT", "1")),
        ember_api_url=env("EMBER_API_URL", "http://127.0.0.1:8030").rstrip("/"),
        admins=frozenset(name.strip().lower() for name in env("BARD_ADMINS", "").split(",") if name.strip()),
    )
