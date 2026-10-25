"""The Bard server: two MCP tools, an audio file route and a health check."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from src.admin_gate import AdminGate
from src.config import Settings
from src.contract import DownloadableVoices, DownloadResult, SpeakResult, VoiceList
from src.engine import PiperEngine, TtsEngine
from src.errors import BardError
from src.identity import owner_from_context
from src.middleware import InternalTokenMiddleware
from src.service import AdminCheck, BardService, VoiceSource
from src.store import AudioStore
from src.voices import VoiceLibrary

INSTRUCTIONS = (
    "Text to speech. Call tool_bard_speak with the text to say; the chat shows a player and a download link. "
    "Pass only text a user should hear. Call tool_bard_listVoices to see the installed voices. "
    "tool_bard_listDownloadable and tool_bard_downloadVoice add new voices and are for Bard admins only."
)


def build_app(
    settings: Settings,
    engine: TtsEngine | None = None,
    gate: AdminCheck | None = None,
    library: VoiceSource | None = None,
) -> Starlette:
    engine = engine or PiperEngine(settings.voices_dir, settings.ffmpeg)
    store = AudioStore(settings.audio_dir, settings.ttl_seconds, settings.quota_bytes)
    store.sweep()
    # shortcut: these HTTP clients live as long as the process and are not closed on shutdown.
    gate = gate or AdminGate(httpx.AsyncClient(), settings.ember_api_url, settings.internal_token, settings.admins)
    library = library or VoiceLibrary(httpx.AsyncClient(follow_redirects=True), settings.voices_dir, settings.staging_dir)
    service = BardService(engine, store, settings, library, gate)
    mcp = FastMCP(name="bard", instructions=INSTRUCTIONS, host=settings.host, port=settings.port)

    @mcp.tool(meta={"keywords": ["speak", "say", "read aloud", "tts", "voice", "audio"], "display_label": "Generating speech"})
    async def tool_bard_speak(
        text: Annotated[str, Field(description="The text to speak. Markdown is stripped; code blocks are skipped.")],
        voice: Annotated[str | None, Field(description="An installed voice name. Omit it for the default voice.")] = None,
        ctx: Context = None,
    ) -> SpeakResult:
        """Turn text into spoken English (MP3). Creates an audio file owned by the asking user; the chat shows
        a player and a download link, so do not paste a link yourself. Returns the file id, duration and a summary."""
        try:
            return await service.speak(owner_from_context(ctx), text, voice)
        except BardError as error:
            raise ToolError(str(error)) from error

    @mcp.tool(
        meta={"keywords": ["voices", "tts"], "display_label": "Listing voices"},
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def tool_bard_listVoices() -> VoiceList:
        """List the installed voices and the default one. Read-only."""
        return await service.list_voices()

    @mcp.tool(
        meta={"keywords": ["voices", "download", "catalog", "tts", "admin"], "display_label": "Listing downloadable voices"},
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    )
    async def tool_bard_listDownloadable(
        language: Annotated[str | None, Field(description="Keep only this language: a family like 'en' or a code like 'en_GB'. Omit for all (about 180 voices).")] = None,
        quality: Annotated[Literal["x_low", "low", "medium", "high"] | None, Field(description="Keep only this quality tier. Omit for all.")] = None,
        ctx: Context = None,
    ) -> DownloadableVoices:
        """Bard admins only. List the voices that can be downloaded onto the Bard machine, with language, quality,
        size and whether each is already installed. Pass a language to keep the list short."""
        try:
            return await service.list_downloadable(owner_from_context(ctx), language, quality)
        except BardError as error:
            raise ToolError(str(error)) from error

    @mcp.tool(
        meta={"keywords": ["voices", "download", "install", "tts", "admin"], "display_label": "Downloading a voice"},
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    )
    async def tool_bard_downloadVoice(
        voice: Annotated[str, Field(description="A voice name from tool_bard_listDownloadable, for example en_US-ryan-high.")],
        ctx: Context = None,
    ) -> DownloadResult:
        """Bard admins only. Download one voice onto the Bard machine (tens of megabytes) so it can be used with
        tool_bard_speak. Refuses a voice that is already installed. Ask the user before downloading."""
        try:
            return await service.download_voice(owner_from_context(ctx), voice)
        except BardError as error:
            raise ToolError(str(error)) from error

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api/files/{file_id}", methods=["GET"])
    async def audio(request: Request) -> Response:
        owner = request.headers.get("x-requester-username", "").strip()
        if not owner:
            return JSONResponse({"error": "identity_required"}, status_code=401)
        file_id = request.path_params["file_id"]
        stored = await asyncio.to_thread(store.get, owner, file_id)
        if stored is None:
            return JSONResponse({"error": "file_not_found"}, status_code=404)
        return FileResponse(
            stored.path,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'inline; filename="bard-{file_id[:8]}.mp3"',
            },
        )

    app = mcp.streamable_http_app()
    app.add_middleware(InternalTokenMiddleware, token=settings.internal_token)
    return app
