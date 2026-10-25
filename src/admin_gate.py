"""Who may install voices: ask ember_api whether a username holds `bard.admin`.

The answer is cached briefly, so a granted or revoked permission takes effect within
`ttl_seconds`. Every failure means "not an admin" and is not cached."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)


class AdminGate:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token: str,
        static_admins: frozenset[str] = frozenset(),
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._url = f"{base_url.rstrip('/')}/api/bard/internal/admin-check"
        self._token = token
        self._static = static_admins
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[bool, float]] = {}

    async def is_admin(self, username: str) -> bool:
        key = username.strip().lower()
        if not key:
            return False
        if key in self._static:
            return True
        cached = self._cache.get(key)
        if cached is not None and cached[1] > self._clock():
            return cached[0]
        answer = await self._ask(username.strip())
        if answer is None:
            return False
        self._cache[key] = (answer, self._clock() + self._ttl)
        return answer

    async def _ask(self, username: str) -> bool | None:
        if not self._token:
            return None  # ember_api only answers a caller that proves the shared token
        try:
            response = await self._client.post(
                self._url, json={"username": username}, headers={"X-Internal-Token": self._token}, timeout=5
            )
            body = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("admin check failed: %s", type(error).__name__)
            return None
        if isinstance(body, dict) and isinstance(body.get("admin"), bool):
            return body["admin"]
        logger.warning("admin check returned status %s or an unexpected body", response.status_code)
        return None
