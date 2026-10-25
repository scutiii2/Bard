from types import SimpleNamespace

from src.identity import owner_from_context


def ctx(meta):
    return SimpleNamespace(request_context=SimpleNamespace(meta=meta))


def test_reads_the_trimmed_requester_username():
    meta = SimpleNamespace(model_extra={"requester": {"username": " ann ", "email": "a@x"}})
    assert owner_from_context(ctx(meta)) == "ann"


def test_no_meta_means_no_owner():
    assert owner_from_context(ctx(None)) == ""


def test_malformed_requester_means_no_owner():
    assert owner_from_context(ctx(SimpleNamespace(model_extra={"requester": "ann"}))) == ""
    assert owner_from_context(ctx(SimpleNamespace(model_extra={"requester": {"username": 7}}))) == ""
    assert owner_from_context(ctx(SimpleNamespace(model_extra=None))) == ""
