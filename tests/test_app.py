import pytest
from starlette.testclient import TestClient

from src.app import build_app
from src.config import Settings
from src.store import AudioStore
from tests.fakes import FakeEngine

TOKEN = {"X-Internal-Token": "tok"}
BOB = {**TOKEN, "X-Requester-Username": "bob"}
ANN = {**TOKEN, "X-Requester-Username": "ann"}


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, internal_token="tok", voice="v1")


@pytest.fixture
def client(settings):
    return TestClient(build_app(settings, engine=FakeEngine()))


@pytest.fixture
def file_id(settings):
    store = AudioStore(settings.audio_dir, settings.ttl_seconds, settings.quota_bytes)
    fid = AudioStore.file_id("v1", "hello")
    store.put("ann", fid, b"0123456789", "v1", 1.0)
    return fid


def test_health_needs_no_token(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"ok": True}


def test_files_require_the_internal_token(client, file_id):
    response = client.get(f"/api/files/{file_id}", headers={"X-Requester-Username": "ann"})
    assert response.status_code == 401
    assert client.get(f"/api/files/{file_id}", headers={"X-Internal-Token": "wrong", "X-Requester-Username": "ann"}).status_code == 401


def test_files_require_a_requester(client, file_id):
    assert client.get(f"/api/files/{file_id}", headers=TOKEN).status_code == 401


def test_the_owner_gets_the_audio(client, file_id):
    response = client.get(f"/api/files/{file_id}", headers=ANN)
    assert response.status_code == 200
    assert response.content == b"0123456789"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_range_requests_are_served(client, file_id):
    response = client.get(f"/api/files/{file_id}", headers={**ANN, "Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"


def test_another_owner_a_missing_id_and_a_malformed_id_all_answer_404(client, file_id):
    assert client.get(f"/api/files/{file_id}", headers=BOB).status_code == 404
    assert client.get(f"/api/files/{'a' * 32}", headers=ANN).status_code == 404
    assert client.get("/api/files/not-an-id", headers=ANN).status_code == 404


def test_without_a_configured_token_the_routes_are_open(tmp_path):
    settings = Settings(data_dir=tmp_path, internal_token="", voice="v1")
    store = AudioStore(settings.audio_dir, settings.ttl_seconds, settings.quota_bytes)
    fid = AudioStore.file_id("v1", "hello")
    store.put("ann", fid, b"abc", "v1", 1.0)
    client = TestClient(build_app(settings, engine=FakeEngine()))
    assert client.get(f"/api/files/{fid}", headers={"X-Requester-Username": "ann"}).status_code == 200
