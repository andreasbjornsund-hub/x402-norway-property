"""Shared pytest fixtures for x402-norway-property."""
import os
import sys

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="session")
def main_module():
    os.environ.setdefault("EVM_ADDRESS", "0xTEST0000000000000000000000000000000000")
    os.chdir(REPO_ROOT)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    import main
    return main


@pytest.fixture
def parsers_module(main_module):
    import parsers
    return parsers


@pytest.fixture
def distance_module(main_module):
    import distance
    return distance


@pytest.fixture
def municipalities_module(main_module):
    import municipalities
    return municipalities


@pytest.fixture(autouse=True)
def reset_cache(main_module):
    import cache
    cache.reset()
    yield


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class FakeKV:
    """Stub for httpx.AsyncClient — Kartverket only uses GET."""

    def __init__(self):
        self.responses: dict[str, FakeResponse] = {}
        self.calls: list[tuple[str, dict]] = []

    def stub(self, url_contains, status, json_data=None):
        self.responses[url_contains] = FakeResponse(status, json_data)

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        for needle, r in self.responses.items():
            if needle in url:
                return r
        return FakeResponse(404, {"error": f"unstubbed {url}"})

    async def aclose(self):
        pass


@pytest.fixture
def fake_kv(main_module, monkeypatch):
    f = FakeKV()
    monkeypatch.setattr(main_module, "_http", f)
    return f
