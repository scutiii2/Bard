import asyncio

import pytest

from src.config import Settings
from src.errors import AdminRequired, DeleteFailed, IdentityRequired, TextRejected, VoiceNotInCatalog, VoiceUnavailable
from src.service import BardService
from src.store import AudioStore
from tests.fakes import FakeEngine, FakeGate, FakeLibrary


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def gate():
    return FakeGate()


@pytest.fixture
def library():
    return FakeLibrary()


@pytest.fixture
def delete_gate():
    return FakeGate()


@pytest.fixture
def service(engine, gate, library, delete_gate, tmp_path):
    settings = Settings(data_dir=tmp_path, voice="v1", max_chars=50)
    return BardService(engine, AudioStore(tmp_path / "audio", 60, 10_000), settings, library, gate, delete_gate)


async def test_speak_synthesizes_stores_and_describes(service, engine):
    result = await service.speak("ann", "Hello **world**", None)
    assert engine.calls == [("Hello world", "v1")]
    assert result.voice == "v1" and result.duration_s == 2.0 and result.cached is False
    assert result.size_bytes == len(b"mp3:Hello world")
    assert "Speech ready" in result.message and "v1" in result.message


async def test_the_second_identical_request_is_a_cache_hit(service, engine):
    first = await service.speak("ann", "Hello", None)
    second = await service.speak("ann", "Hello", None)
    assert second.cached is True and second.file_id == first.file_id
    assert len(engine.calls) == 1


async def test_identical_concurrent_requests_synthesize_once(service, engine):
    await asyncio.gather(service.speak("ann", "same text", None), service.speak("ann", "same text", None))
    assert len(engine.calls) == 1


async def test_owners_do_not_share_audio(service, engine):
    await service.speak("ann", "Hello", None)
    await service.speak("bob", "Hello", None)
    assert len(engine.calls) == 2


async def test_an_explicit_voice_is_used(service, engine):
    result = await service.speak("ann", "Hello", "v2")
    assert result.voice == "v2" and engine.calls == [("Hello", "v2")]


async def test_missing_identity_is_refused_before_any_work(service, engine):
    with pytest.raises(IdentityRequired):
        await service.speak("", "Hello", None)
    assert engine.calls == []


async def test_unknown_voice_is_refused_before_any_work(service, engine):
    with pytest.raises(VoiceUnavailable):
        await service.speak("ann", "Hello", "nope")
    assert engine.calls == []


async def test_text_over_the_limit_is_rejected(service, engine):
    with pytest.raises(TextRejected):
        await service.speak("ann", "x" * 51, None)
    assert engine.calls == []


async def test_list_voices_reports_voices_and_the_default(service):
    result = await service.list_voices()
    assert result.voices == ["v1", "v2"] and result.default == "v1"
    assert "v1" in result.message


async def test_listing_downloadable_voices_is_for_admins_only(service, gate, library):
    with pytest.raises(AdminRequired):
        await service.list_downloadable("ann", None, None)
    assert library.listed == []
    gate.admins.add("ann")
    result = await service.list_downloadable("ann", "en", "high")
    assert library.listed == [("en", "high")]
    assert [v.voice for v in result.voices] == ["en_US-ryan-high", "en_GB-alba-medium"]
    assert "2 voice" in result.message and "1 already installed" in result.message


async def test_downloading_a_voice_is_for_admins_only(service, gate, library):
    with pytest.raises(AdminRequired):
        await service.download_voice("ann", "en_US-ryan-high")
    assert library.installed == []
    gate.admins.add("ann")
    result = await service.download_voice("ann", "en_US-ryan-high")
    assert library.installed == ["en_US-ryan-high"]
    assert result.voice == "en_US-ryan-high" and result.size_mb == 114.2
    assert "tool_bard_speak" in result.message


async def test_deleting_a_voice_needs_the_delete_permission_not_just_admin(service, gate, delete_gate, library, engine):
    gate.admins.add("ann")  # bard.admin alone is not enough
    with pytest.raises(AdminRequired, match="bard.delete"):
        await service.delete_voice("ann", "v2")
    assert library.removed == [] and engine.unloaded == []
    delete_gate.admins.add("ann")
    result = await service.delete_voice("ann", "v2")
    assert library.removed == ["v2"] and engine.unloaded == ["v2"]
    assert result.voice == "v2" and "Deleted v2" in result.message


async def test_the_default_voice_cannot_be_deleted(service, delete_gate, library):
    delete_gate.admins.add("ann")
    with pytest.raises(DeleteFailed, match="default voice"):
        await service.delete_voice("ann", "v1")
    assert library.removed == []


async def test_delete_needs_an_identity_before_the_gate_is_asked(service, delete_gate):
    with pytest.raises(IdentityRequired):
        await service.delete_voice("", "v2")
    assert delete_gate.asked == []


async def test_admin_tools_need_an_identity_before_the_gate_is_asked(service, gate):
    with pytest.raises(IdentityRequired):
        await service.list_downloadable("", None, None)
    with pytest.raises(IdentityRequired):
        await service.download_voice("", "en_US-ryan-high")
    assert gate.asked == []


async def test_voice_library_errors_reach_the_caller(service, gate):
    gate.admins.add("ann")
    with pytest.raises(VoiceNotInCatalog):
        await service.download_voice("ann", "nope")
