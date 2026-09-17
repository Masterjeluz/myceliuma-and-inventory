"""BIG #29 transport tests: URL hardening + providers.

No network in these tests: validation is pure, fetching is
exercised through the TEST provider and a stub httpx client.
"""

import pytest

from coordinator.app.research_transport import (
    SEARCH_ALLOWLIST,
    TestResearchTransport,
    TransportRefusedError,
    TransportUnavailableError,
    UnavailableSearchProvider,
    WikipediaSearchProvider,
    fetch_url,
    validate_url,
)


def test_public_https_validates():
    url = validate_url("https://en.wikipedia.org/wiki/Camper")
    assert url.startswith("https://en.wikipedia.org/")


def test_scheme_required():
    with pytest.raises(TransportRefusedError):
        validate_url("en.wikipedia.org/wiki/X")


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,hi",
    "ftp://example.com/x",
    "gopher://example.com/",
])
def test_dangerous_schemes_refuse(bad):
    with pytest.raises(TransportRefusedError):
        validate_url(bad)


@pytest.mark.parametrize("bad", [
    "http://localhost/x",
    "http://localhost.localdomain/x",
    "http://127.0.0.1/x",
    "http://127.0.0.2:8080/x",
    "http://10.0.0.5/x",
    "http://192.168.1.1/x",
    "http://172.16.0.9/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/x",
    "http://[::1]/x",
    "http://[fe80::1]/x",
    "http://user:pass@example.com/x",
    "http://2130706433/x",  # decimal 127.0.0.1
    "http://0x7f.0x0.0x0.0x1/x",  # hex 127.0.0.1
    "http://2130706433.0.0.0/x",
    "http://example.local/x",
    "http://host.internal/x",
])
def test_ssrf_surface_refuses(bad):
    with pytest.raises(TransportRefusedError):
        validate_url(bad)


def test_allowlist_enforced():
    with pytest.raises(TransportRefusedError):
        validate_url("https://example.com/x",
                     allow_hosts=SEARCH_ALLOWLIST)
    ok = validate_url("https://nl.wikipedia.org/wiki/Camper",
                      allow_hosts=SEARCH_ALLOWLIST)
    assert "nl.wikipedia.org" in ok


def test_url_too_long_refuses():
    with pytest.raises(TransportRefusedError):
        validate_url("https://example.com/" + "a" * 2000)


def test_unavailable_names_missing_capability():
    provider = UnavailableSearchProvider()
    assert provider.execution_state == "UNAVAILABLE"
    assert "missing" in provider.capabilities()
    with pytest.raises(TransportUnavailableError):
        provider.search("camper")


def test_test_provider_deterministic():
    pages = {"camper": ("Camper onderhoud",
                        "De camper heeft een distributieriem. "
                        "De riem is belangrijk voor de motor.")}
    provider = TestResearchTransport(pages)
    hits = provider.search("distributieriem camper")
    assert len(hits) == 1
    assert hits[0].execution_state == "TEST"
    page = provider.fetch("https://test.example/camper")
    assert page.execution_state == "TEST"
    assert "distributieriem" in page.text
    with pytest.raises(TransportUnavailableError):
        provider.fetch("https://test.example/missing")


def test_wikipedia_rejects_language():
    with pytest.raises(TransportRefusedError):
        WikipediaSearchProvider(language="xx")


class _StubResponse:
    def __init__(self, status=200, body=b"hello world",
                 content_type="text/plain", location=""):
        self.status_code = status
        self.content = body
        self.headers = {"content-type": content_type,
                        "location": location}


class _StubClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, timeout=None):
        self.calls.append(url)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def test_fetch_real_labels_real():
    client = _StubClient([_StubResponse(body=b"camper text")])
    page = fetch_url("https://example.com/camper", client=client)
    assert page.execution_state == "REAL"
    assert page.text == "camper text"
    assert client.closed is False  # caller-owned client stays open


def test_fetch_redirect_revalidated_and_capped():
    hops = [_StubResponse(status=302, location="/next")
            for _ in range(5)]
    client = _StubClient(hops)
    with pytest.raises(TransportRefusedError):
        fetch_url("https://example.com/a", client=client)


def test_fetch_redirect_to_private_refuses():
    client = _StubClient([
        _StubResponse(status=302,
                      location="http://127.0.0.1/secret")])
    with pytest.raises(TransportRefusedError):
        fetch_url("https://example.com/a", client=client)


def test_fetch_executable_refuses():
    client = _StubClient([
        _StubResponse(content_type="application/x-msdownload",
                      body=b"MZ")])
    with pytest.raises(TransportRefusedError):
        fetch_url("https://example.com/setup.exe", client=client)


def test_fetch_body_capped():
    from coordinator.app.research_transport import MAX_BODY_BYTES
    client = _StubClient([
        _StubResponse(body=b"x" * (MAX_BODY_BYTES + 100))])
    page = fetch_url("https://example.com/big", client=client)
    assert len(page.text.encode("utf-8")) <= MAX_BODY_BYTES


def test_fetch_failure_is_unavailable_not_fake():
    client = _StubClient([TimeoutError("slow")])
    with pytest.raises(TransportUnavailableError):
        fetch_url("https://example.com/a", client=client)
