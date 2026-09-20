from core.network import NetworkClient, enforce_direct_network_env
from core.settings import AppSettings


class FakeResponse:
    ok = True
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict:
        return {"ok": True}


class FakeSession:
    def __init__(self) -> None:
        self.posts: list[str] = []
        self.gets: list[str] = []

    def post(self, url: str, **_kwargs) -> FakeResponse:
        self.posts.append(url)
        return FakeResponse()

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.gets.append(url)
        return FakeResponse()


class FakeRequestsModule:
    last_session: FakeSession | None = None

    @classmethod
    def Session(cls) -> FakeSession:
        cls.last_session = FakeSession()
        return cls.last_session

    @staticmethod
    def post(_url: str, **_kwargs) -> FakeResponse:
        raise AssertionError("NetworkClient should reuse Session.post")

    @staticmethod
    def get(_url: str, **_kwargs) -> FakeResponse:
        raise AssertionError("NetworkClient should reuse Session.get")


def test_network_client_reuses_requests_session_for_json_requests() -> None:
    client = NetworkClient(
        settings=AppSettings(proxy_mode="none"),
        requests_module=FakeRequestsModule,
    )

    result = client.request_json(
        "POST",
        "https://example.test/api",
        headers={},
        payload={},
    )

    assert result == {"ok": True}
    assert FakeRequestsModule.last_session is not None
    assert FakeRequestsModule.last_session.posts == ["https://example.test/api"]


def test_direct_mode_clears_proxy_environment_for_http_and_websocket_sdks(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7890")

    enforce_direct_network_env()

    assert "HTTP_PROXY" not in __import__("os").environ
    assert "HTTPS_PROXY" not in __import__("os").environ
    assert "ALL_PROXY" not in __import__("os").environ
    assert __import__("os").environ["NO_PROXY"] == "*"
