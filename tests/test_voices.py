import asyncio
import hashlib
import types

import httpx
import pytest

from src.errors import CatalogUnavailable, DownloadFailed, VoiceAlreadyInstalled, VoiceNotInCatalog
from src.voices import VoiceLibrary

MODEL = b"model-bytes" * 100
CONFIG = b'{"audio": {"sample_rate": 22050}}'


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def voice_entry(key: str, code: str, quality: str, model: bytes = MODEL, config: bytes = CONFIG):
    family, name = code.split("_")[0], key.split("-")[1]
    base = f"{family}/{code}/{name}/{quality}/{key}"
    meta = {
        "key": key,
        "name": name,
        "language": {"code": code, "family": family, "name_english": "English"},
        "quality": quality,
        "files": {
            f"{base}.onnx": {"size_bytes": len(model), "md5_digest": md5(model)},
            f"{base}.onnx.json": {"size_bytes": len(config), "md5_digest": md5(config)},
            f"{family}/{code}/{name}/{quality}/MODEL_CARD": {"size_bytes": 3, "md5_digest": md5(b"mc")},
        },
    }
    return meta, {f"{base}.onnx": model, f"{base}.onnx.json": config}


class Hub:
    """A fake Hugging Face: voices.json plus the files it lists."""

    def __init__(self) -> None:
        self.catalog: dict = {}
        self.files: dict[str, bytes] = {}
        self.requests: list[str] = []
        self.catalog_status = 200

    def add(self, key, code, quality, **kwargs):
        meta, files = voice_entry(key, code, quality, **kwargs)
        self.catalog[key] = meta
        self.files.update(files)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if request.url.path == "/voices.json":
            return httpx.Response(self.catalog_status, json=self.catalog)
        prefix = "/files/"
        data = self.files.get(request.url.path.removeprefix(prefix)) if request.url.path.startswith(prefix) else None
        return httpx.Response(200, content=data) if data is not None else httpx.Response(404)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def hub():
    hub = Hub()
    hub.add("en_US-ryan-high", "en_US", "high")
    hub.add("en_GB-alba-medium", "en_GB", "medium")
    hub.add("de_DE-thorsten-medium", "de_DE", "medium")
    return hub


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def library(hub, tmp_path, clock):
    client = httpx.AsyncClient(transport=httpx.MockTransport(hub))
    return VoiceLibrary(
        client, tmp_path / "voices", tmp_path / "staging",
        catalog_url="https://hf.test/voices.json", base_url="https://hf.test/files/",
        max_bytes=10_000, catalog_ttl_seconds=60, clock=clock,
    )


async def test_list_returns_every_voice_sorted_with_installed_flags(library, tmp_path):
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "en_US-ryan-high.onnx").write_bytes(b"x")
    entries = await library.list(None, None)
    assert [e.voice for e in entries] == ["de_DE-thorsten-medium", "en_GB-alba-medium", "en_US-ryan-high"]
    assert [e.installed for e in entries] == [False, False, True]
    ryan = entries[2]
    assert (ryan.language, ryan.quality) == ("en_US", "high")
    assert ryan.size_mb == round((len(MODEL) + len(CONFIG)) / 1048576, 1)


async def test_list_filters_by_language_family_or_code_and_by_quality(library):
    assert [e.voice for e in await library.list("en", None)] == ["en_GB-alba-medium", "en_US-ryan-high"]
    assert [e.voice for e in await library.list("EN_gb", None)] == ["en_GB-alba-medium"]
    assert [e.voice for e in await library.list(None, "medium")] == ["de_DE-thorsten-medium", "en_GB-alba-medium"]
    assert await library.list("fr", None) == []


async def test_the_catalog_is_cached_then_refetched(library, hub, clock):
    await library.list(None, None)
    await library.list(None, None)
    assert hub.requests.count("/voices.json") == 1
    clock.now += 61
    await library.list(None, None)
    assert hub.requests.count("/voices.json") == 2


async def test_an_unusable_catalog_is_catalog_unavailable(library, hub):
    hub.catalog_status = 500
    with pytest.raises(CatalogUnavailable):
        await library.list(None, None)


async def test_an_unreachable_catalog_is_catalog_unavailable(tmp_path):
    def down(request):
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    library = VoiceLibrary(client, tmp_path / "v", tmp_path / "s", catalog_url="https://hf.test/voices.json", base_url="https://hf.test/files/")
    with pytest.raises(CatalogUnavailable):
        await library.list(None, None)


async def test_install_writes_both_files_and_cleans_the_staging_area(library, tmp_path):
    voice = await library.install("en_GB-alba-medium")
    voices = tmp_path / "voices"
    assert voice.voice == "en_GB-alba-medium" and voice.installed is True
    assert (voices / "en_GB-alba-medium.onnx").read_bytes() == MODEL
    assert (voices / "en_GB-alba-medium.onnx.json").read_bytes() == CONFIG
    assert not list((tmp_path / "staging").iterdir())
    assert [e.installed for e in await library.list("en_GB", None)] == [True]


@pytest.mark.parametrize("name", ["nope", "../etc/passwd", "en_US-ryan-high/../x", "", "x" * 300])
async def test_install_only_accepts_catalog_names(library, tmp_path, name):
    with pytest.raises(VoiceNotInCatalog):
        await library.install(name)
    assert not (tmp_path / "voices").exists() or not list((tmp_path / "voices").iterdir())


async def test_install_refuses_an_installed_voice(library):
    await library.install("en_GB-alba-medium")
    with pytest.raises(VoiceAlreadyInstalled):
        await library.install("en_GB-alba-medium")


async def test_a_checksum_mismatch_installs_nothing(library, hub, tmp_path):
    key = "en_GB-alba-medium"
    path = next(p for p in hub.files if p.endswith(f"{key}.onnx"))
    hub.files[path] = b"y" * len(MODEL)  # same size, different content
    with pytest.raises(DownloadFailed, match="checksum"):
        await library.install(key)
    assert not (tmp_path / "voices").exists() or not list((tmp_path / "voices").iterdir())
    assert not list((tmp_path / "staging").iterdir())


async def test_a_download_larger_than_declared_is_stopped(library, hub, tmp_path):
    key = "en_GB-alba-medium"
    path = next(p for p in hub.files if p.endswith(f"{key}.onnx"))
    hub.files[path] = MODEL + b"extra"
    with pytest.raises(DownloadFailed, match="size"):
        await library.install(key)
    assert not (tmp_path / "voices").exists() or not list((tmp_path / "voices").iterdir())


async def test_a_failed_second_file_leaves_no_partial_voice(library, hub, tmp_path):
    key = "en_GB-alba-medium"
    del hub.files[next(p for p in hub.files if p.endswith(f"{key}.onnx.json"))]
    with pytest.raises(DownloadFailed):
        await library.install(key)
    assert any(p.endswith(f"{key}.onnx") for p in hub.requests)  # the first file did download
    assert not (tmp_path / "voices").exists() or not list((tmp_path / "voices").iterdir())
    assert not list((tmp_path / "staging").iterdir())


async def test_a_voice_over_the_size_cap_is_refused_before_downloading(hub, tmp_path):
    hub.add("en_US-big-high", "en_US", "high", model=b"z" * 20_000)
    client = httpx.AsyncClient(transport=httpx.MockTransport(hub))
    library = VoiceLibrary(client, tmp_path / "v", tmp_path / "s", catalog_url="https://hf.test/voices.json", base_url="https://hf.test/files/", max_bytes=10_000)
    with pytest.raises(DownloadFailed, match="limit"):
        await library.install("en_US-big-high")
    assert not any(path.startswith("/files/") for path in hub.requests)


async def test_not_enough_disk_space_is_refused_before_downloading(library, hub, monkeypatch):
    monkeypatch.setattr("src.voices.shutil.disk_usage", lambda path: types.SimpleNamespace(free=1))
    with pytest.raises(DownloadFailed, match="disk space"):
        await library.install("en_GB-alba-medium")
    assert not any(path.startswith("/files/") for path in hub.requests)


async def test_two_installs_of_the_same_voice_download_it_once(library, hub):
    results = await asyncio.gather(library.install("en_GB-alba-medium"), library.install("en_GB-alba-medium"), return_exceptions=True)
    assert sum(isinstance(r, VoiceAlreadyInstalled) for r in results) == 1
    assert len([p for p in hub.requests if p.endswith(".onnx")]) == 1
