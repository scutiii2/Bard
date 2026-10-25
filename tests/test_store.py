import pytest

from src.errors import QuotaExceeded
from src.store import AudioStore


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return AudioStore(tmp_path, ttl_seconds=60, quota_bytes=100, clock=clock)


FID = AudioStore.file_id("v", "hello")


def test_file_id_is_stable_32_char_hex_and_depends_on_voice_and_text():
    assert FID == AudioStore.file_id("v", "hello")
    assert len(FID) == 32 and int(FID, 16) >= 0
    assert FID != AudioStore.file_id("w", "hello")
    assert FID != AudioStore.file_id("v", "hello!")


def test_put_then_get_round_trips(store):
    store.put("ann", FID, b"abc", "v", 1.5)
    got = store.get("ann", FID)
    assert got.path.read_bytes() == b"abc"
    assert (got.voice, got.duration_s, got.size_bytes) == ("v", 1.5, 3)


def test_another_owner_gets_nothing(store):
    store.put("ann", FID, b"abc", "v", 1.0)
    assert store.get("bob", FID) is None


def test_malformed_id_is_none(store):
    assert store.get("ann", "../x") is None
    assert store.get("ann", "A" * 32) is None


def test_expired_file_is_removed_on_get(store, clock, tmp_path):
    store.put("ann", FID, b"abc", "v", 1.0)
    clock.now += 61
    assert store.get("ann", FID) is None
    assert not list(tmp_path.rglob("*.mp3"))


def test_put_rejects_a_write_over_the_quota(store):
    store.put("ann", FID, b"x" * 60, "v", 1.0)
    with pytest.raises(QuotaExceeded):
        store.put("ann", AudioStore.file_id("v", "other"), b"x" * 60, "v", 1.0)


def test_put_frees_expired_files_before_checking_the_quota(store, clock):
    store.put("ann", FID, b"x" * 60, "v", 1.0)
    clock.now += 61
    store.put("ann", AudioStore.file_id("v", "other"), b"x" * 60, "v", 1.0)


def test_sweep_removes_expired_files_for_every_owner(store, clock):
    store.put("ann", FID, b"abc", "v", 1.0)
    store.put("bob", FID, b"abc", "v", 1.0)
    clock.now += 61
    assert store.sweep() == 2
    assert store.sweep() == 0
