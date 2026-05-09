"""Shared pytest fixtures."""
import os
import sys

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="session")
def main_module():
    """Import main.py with stubbed env so it doesn't talk to anything real."""
    os.environ.setdefault("EVM_ADDRESS", "0xTEST0000000000000000000000000000000000")

    os.chdir(REPO_ROOT)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    import main
    return main


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data


class FakeHTTPClient:
    """Records calls and returns canned responses keyed by URL substring."""

    def __init__(self):
        self.responses: dict[str, FakeResponse] = {}
        self.calls: list[tuple[str, dict]] = []

    def stub(self, url_contains: str, status_code: int, json_data: dict | None = None):
        self.responses[url_contains] = FakeResponse(status_code, json_data)

    async def get(self, url: str, params: dict | None = None) -> FakeResponse:
        self.calls.append((url, params or {}))
        for needle, resp in self.responses.items():
            if needle in url:
                return resp
        return FakeResponse(404, {"error": f"unstubbed url: {url}"})

    async def aclose(self):
        pass


@pytest.fixture
def fake_http(main_module, monkeypatch):
    """Replace main._http with a FakeHTTPClient."""
    fake = FakeHTTPClient()
    monkeypatch.setattr(main_module, "_http", fake)
    return fake
