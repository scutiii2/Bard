import pytest

from src import run


def test_refuses_to_start_exposed_without_a_token(monkeypatch):
    monkeypatch.setenv("BARD_HOST", "0.0.0.0")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    with pytest.raises(SystemExit, match="INTERNAL_API_TOKEN"):
        run.main()
