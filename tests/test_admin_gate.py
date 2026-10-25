import httpx

from src.admin_gate import AdminGate


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_gate(handler, *, token="tok", static=frozenset(), clock=None, permission=None):
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
    gate = AdminGate(client, "http://ember.test", token, static, ttl_seconds=30, clock=clock or Clock(), permission=permission)
    return gate, requests


def admin(request):
    return httpx.Response(200, json={"admin": True})


def not_admin(request):
    return httpx.Response(200, json={"admin": False})


async def test_an_admin_is_allowed_and_ember_api_gets_the_token_and_username():
    gate, requests = make_gate(admin)
    assert await gate.is_admin("ann") is True
    sent = requests[0]
    assert sent.url == "http://ember.test/api/bard/internal/admin-check"
    assert sent.headers["x-internal-token"] == "tok"
    assert sent.read() == b'{"username":"ann"}'


async def test_a_non_admin_is_denied():
    gate, _ = make_gate(not_admin)
    assert await gate.is_admin("ann") is False


async def test_answers_are_cached_until_the_ttl_passes():
    clock = Clock()
    gate, requests = make_gate(admin, clock=clock)
    await gate.is_admin("ann")
    await gate.is_admin("ann")
    assert len(requests) == 1
    clock.now += 31
    await gate.is_admin("ann")
    assert len(requests) == 2


async def test_a_revoked_admin_is_denied_after_the_ttl():
    clock = Clock()
    answers = iter([True, False])
    gate, _ = make_gate(lambda r: httpx.Response(200, json={"admin": next(answers)}), clock=clock)
    assert await gate.is_admin("ann") is True
    clock.now += 31
    assert await gate.is_admin("ann") is False


async def test_fails_closed_on_server_errors_bad_bodies_and_unreachable_ember_api():
    def down(request):
        raise httpx.ConnectError("down")

    for handler in (
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(401, json={"admin": True}),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"admin": "yes"}),
        lambda r: httpx.Response(200, json=["admin"]),
        down,
    ):
        gate, _ = make_gate(handler)
        assert await gate.is_admin("ann") is False


async def test_failures_are_not_cached():
    answers = iter([httpx.Response(500), httpx.Response(200, json={"admin": True})])
    gate, requests = make_gate(lambda r: next(answers))
    assert await gate.is_admin("ann") is False
    assert await gate.is_admin("ann") is True
    assert len(requests) == 2


async def test_a_permission_gate_names_the_permission_it_asks_about():
    gate, requests = make_gate(admin, permission="bard.delete")
    assert await gate.is_admin("ann") is True
    assert requests[0].read() == b'{"username":"ann","permission":"bard.delete"}'


async def test_an_empty_username_is_denied_without_a_request():
    gate, requests = make_gate(admin)
    assert await gate.is_admin("  ") is False
    assert requests == []


async def test_static_admins_are_allowed_case_insensitively_without_a_request():
    gate, requests = make_gate(not_admin, static=frozenset({"ann"}))
    assert await gate.is_admin("Ann") is True
    assert requests == []


async def test_without_a_token_ember_api_is_not_asked():
    gate, requests = make_gate(admin, token="")
    assert await gate.is_admin("ann") is False
    assert requests == []
