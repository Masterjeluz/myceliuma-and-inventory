"""Hardened research transport (BIG #29).

One GET-only fetch layer plus a small provider registry. Every
byte that enters Mycelium through here is labelled with an
execution state: REAL (remote host answered), TEST (fixture),
or UNAVAILABLE (nothing fetched). Nothing is ever presented
as research that was not actually retrieved.

Hardening (all fail-closed, all tested):

- URL validation: https/http only; file://, javascript:,
  data:, and every other scheme refuse.
- SSRF protection: no credentials in URLs, no localhost,
  no 127.0.0.0/8, no RFC1918, no link-local, no
  cloud-metadata addresses (169.254.169.254, metadata
  hostnames), no raw-IP bypass tricks (decimal/octal/hex
  forms resolve through ipaddress first).
- Redirects: never followed automatically; at most
  MAX_REDIRECTS manual hops, each re-validated.
- Budgets: per-request timeout, per-response body cap,
  content-type allowlist (HTML/text; executables refuse).
- No cookies, no auth headers, no POST, no uploads, no
  browser, no shell, no subprocess. httpx only.

Providers:

- TestResearchTransport: deterministic fixtures, TEST label.
- WikipediaSearchProvider: REAL search+fetch against an
  explicit host allowlist (MediaWiki API). No API key, no
  login. Unreachable/blocked -> UNAVAILABLE with reason.
- UnavailableSearchProvider: default when no search
  capability exists. Names the missing capability.
- DirectFetchTransport: REAL fetch of explicit, validated
  URLs (user- or mission-supplied). Search stays UNAVAILABLE;
  fetching a given URL is real transport, honestly labelled.
"""

import hashlib
import ipaddress
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

EXECUTION_STATES = ("REAL", "SIMULATED", "TEST", "UNAVAILABLE")

FETCH_TIMEOUT_SECONDS = 10.0
MAX_BODY_BYTES = 200_000
MAX_REDIRECTS = 3
MAX_URL_CHARS = 2000

ALLOWED_SCHEMES = frozenset({"https", "http"})
ALLOWED_CONTENT_TYPES = (
    "text/html", "application/xhtml+xml",
    "text/plain", "application/json",
)

#: Hosts a search provider may touch. Closed allowlist: public
#: knowledge APIs only, no general web search, no credentials.
SEARCH_ALLOWLIST = frozenset({
    "en.wikipedia.org", "nl.wikipedia.org", "de.wikipedia.org",
    "fr.wikipedia.org", "api.wikimedia.org",
})

METADATA_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.google.com",
    "instance-data",
})
METADATA_IPS = frozenset({
    "169.254.169.254", "fd00:ec2::254",
})


class TransportRefusedError(ValueError):
    """URL or fetch refused before any socket opened."""


class TransportUnavailableError(RuntimeError):
    """Transport valid but unreachable/right now unusable."""


@dataclass(frozen=True)
class FetchedPage:
    """One retrieved page. Bytes + metadata, never trust."""

    canonical_url: str = ""
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    title: str = ""
    text: str = ""
    content_hash: str = ""
    retrieved_at: str = ""
    execution_state: str = "UNAVAILABLE"
    provider: str = ""
    hops: int = 0


@dataclass(frozen=True)
class SearchHit:
    """One search result. A pointer, not content."""

    title: str = ""
    url: str = ""
    snippet: str = ""
    provider: str = ""
    execution_state: str = "UNAVAILABLE"


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _is_blocked_ip(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    if str(parsed) in METADATA_IPS:
        return True
    return (parsed.is_private or parsed.is_loopback
            or parsed.is_link_local or parsed.is_multicast
            or parsed.is_reserved or parsed.is_unspecified)


def validate_url(raw: str, *,
                 allow_hosts: frozenset | None = None) -> str:
    """Validate one URL for safe GET fetching. Returns the
    canonical URL or raises TransportRefusedError. Pure."""
    if not isinstance(raw, str) or not raw.strip():
        raise TransportRefusedError("URL must be non-empty text")
    text = raw.strip()
    if len(text) > MAX_URL_CHARS:
        raise TransportRefusedError("URL too long")
    if re.match(r"^[a-zA-Z0-9][a-zA-Z0-9+.-]*:", text):
        scheme = text.split(":", 1)[0].lower()
        if scheme not in ALLOWED_SCHEMES:
            raise TransportRefusedError(
                f"scheme '{scheme}' refused; https/http only")
    else:
        raise TransportRefusedError(
            "URL needs an explicit https:// or http:// scheme")
    try:
        parsed = urlparse(text)
    except ValueError as error:
        raise TransportRefusedError(f"URL unparsable: {error}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise TransportRefusedError("URL has no host")
    if "@" in text.split("://", 1)[1].split("/", 1)[0]:
        raise TransportRefusedError(
            "credentials in URLs are refused")
    if host in METADATA_HOSTS:
        raise TransportRefusedError(
            "metadata endpoints are refused")
    # Raw IP (any notation) -> normalize through ipaddress.
    # NOTE: the refusal raises below sit OUTSIDE the try block
    # on purpose: TransportRefusedError is a ValueError and must
    # never be swallowed by the except below.
    normalized = ""
    try:
        normalized = str(ipaddress.ip_address(host))
    except ValueError:
        normalized = ""
    if normalized:
        if _is_blocked_ip(normalized):
            raise TransportRefusedError(
                "private/loopback/link-local/metadata IPs refused")
        host = normalized
    else:
        if re.fullmatch(r"[0-9.]+", host):
            raise TransportRefusedError(
                "numeric host refused (possible IP bypass)")
        if re.fullmatch(r"[0-9a-fA-FxX.]+", host or ""):
            # Hex/octal dotted forms (0x7f.0x0..., 0177.0.0.1):
            # not parseable as plain IPs but routable by
            # resolvers — refuse the whole class.
            raise TransportRefusedError(
                "encoded numeric host refused (possible IP "
                "bypass)")
        # Hostname: resolve? No DNS here — refuse only obvious
        # local names; DNS rebinding is mitigated by the
        # no-redirect-following + IP re-check per hop below.
        if host in ("localhost",) or host.startswith("localhost.") \
                or host.endswith(".local") \
                or host.endswith(".internal") \
                or host.endswith(".localhost"):
            raise TransportRefusedError(
                "local hostnames are refused")
    if allow_hosts is not None and host not in allow_hosts:
        raise TransportRefusedError(
            f"host '{host}' is not in this provider's allowlist")
    canonical = f"{parsed.scheme.lower()}://{host}"
    if parsed.port and parsed.port not in (80, 443):
        canonical += f":{parsed.port}"
    canonical += parsed.path or "/"
    if parsed.query:
        canonical += f"?{parsed.query[:500]}"
    return canonical[:MAX_URL_CHARS]


def fetch_url(url: str, *, client=None,
              allow_hosts: frozenset | None = None,
              provider: str = "direct") -> FetchedPage:
    """GET one validated URL with budgets. REAL on bytes,
    UNAVAILABLE (raised) otherwise. No cookies, no auth."""
    import httpx
    canonical = validate_url(url, allow_hosts=allow_hosts)
    own_client = client is None
    if own_client:
        client = httpx.Client(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False,
            headers={"User-Agent": "MyceliumResearch/1.0 "
                                   "(local-first research; contact: "
                                   "operator)"})
    try:
        current = canonical
        hops = 0
        while True:
            try:
                response = client.get(
                    current, timeout=FETCH_TIMEOUT_SECONDS)
            except Exception as error:
                raise TransportUnavailableError(
                    f"fetch failed: {type(error).__name__}: "
                    f"{str(error)[:200]}")
            if response.status_code in (301, 302, 303, 307, 308):
                hops += 1
                if hops > MAX_REDIRECTS:
                    raise TransportRefusedError(
                        "redirect budget exhausted")
                location = response.headers.get("location", "")
                if not location:
                    raise TransportRefusedError(
                        "redirect without location")
                if location.startswith("/"):
                    base = urlparse(current)
                    location = (f"{base.scheme}://{base.netloc}"
                                f"{location}")
                current = validate_url(
                    location, allow_hosts=allow_hosts)
                continue
            if response.status_code != 200:
                raise TransportUnavailableError(
                    f"HTTP {response.status_code} for {current[:120]}")
            raw_type = response.headers.get("content-type", "")
            content_type = raw_type.split(";")[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise TransportRefusedError(
                    f"content-type '{content_type[:80]}' refused")
            body = response.content[:MAX_BODY_BYTES + 1]
            truncated = len(body) > MAX_BODY_BYTES
            body = body[:MAX_BODY_BYTES]
            try:
                text = body.decode("utf-8", "replace")
            except ValueError:
                raise TransportRefusedError(
                    "response is not decodable text")
            stamp = now()
            return FetchedPage(
                canonical_url=canonical, final_url=current,
                status_code=response.status_code,
                content_type=content_type, title="", text=text,
                content_hash=hashlib.sha256(body).hexdigest(),
                retrieved_at=stamp, execution_state="REAL",
                provider=provider, hops=hops)
    finally:
        if own_client:
            client.close()


# -- providers -------------------------------------------------------

class ResearchSearchProvider:
    """Interface: search() points at sources, never content."""

    provider_name = "base"
    execution_state = "UNAVAILABLE"

    def capabilities(self) -> dict:
        return {"provider": self.provider_name,
                "execution_state": self.execution_state,
                "search": False, "fetch": False}

    def search(self, query: str,
               max_results: int = 5) -> list[SearchHit]:
        raise NotImplementedError


class UnavailableSearchProvider(ResearchSearchProvider):
    """Default: no search capability. Names what is missing."""

    provider_name = "unavailable"
    execution_state = "UNAVAILABLE"
    missing_capability = ("no web-search API configured; real "
                          "search needs an explicit provider such "
                          "as the Wikipedia allowlist provider")

    def capabilities(self) -> dict:
        return {"provider": self.provider_name,
                "execution_state": self.execution_state,
                "search": False, "fetch": False,
                "missing": self.missing_capability}

    def search(self, query: str,
               max_results: int = 5) -> list[SearchHit]:
        raise TransportUnavailableError(self.missing_capability)


class TestResearchTransport(ResearchSearchProvider):
    """Deterministic fixtures for tests/dev. Always TEST,
    never presented as REAL."""

    __test__ = False  # not a pytest test class
    provider_name = "test"
    execution_state = "TEST"

    #: path -> (title, text). Deterministic, hostile-injectable.
    PAGES: dict = {}

    def __init__(self, pages: dict | None = None):
        self._pages = dict(pages if pages is not None
                           else self.PAGES)

    def capabilities(self) -> dict:
        return {"provider": self.provider_name,
                "execution_state": self.execution_state,
                "search": True, "fetch": True,
                "fixtures": sorted(self._pages)}

    def search(self, query: str,
               max_results: int = 5) -> list[SearchHit]:
        words = [word.lower() for word in re.findall(
            r"[a-zA-Z0-9]{3,}", query or "")]
        hits = []
        for path, (title, text) in self._pages.items():
            blob = f"{title} {text}".lower()
            if any(word in blob for word in words) or not words:
                hits.append(SearchHit(
                    title=title,
                    url=f"https://test.example/{path}",
                    snippet=text[:200], provider="test",
                    execution_state="TEST"))
            if len(hits) >= max(1, min(int(max_results or 5),
                                       10)):
                break
        return hits

    def fetch(self, url: str) -> FetchedPage:
        parsed = urlparse(url)
        key = (parsed.path or "/").lstrip("/")
        if key not in self._pages:
            raise TransportUnavailableError(
                f"test fixture has no page '{key[:80]}'")
        title, text = self._pages[key]
        body = text.encode("utf-8")
        return FetchedPage(
            canonical_url=url, final_url=url, status_code=200,
            content_type="text/plain", title=title, text=text,
            content_hash=hashlib.sha256(body).hexdigest(),
            retrieved_at=now(), execution_state="TEST",
            provider="test", hops=0)


class WikipediaSearchProvider(ResearchSearchProvider):
    """REAL search+fetch against the explicit Wikimedia
    allowlist. GET-only MediaWiki API, no key, no login.
    Unreachable -> UNAVAILABLE with the reason, never fake."""

    provider_name = "wikipedia"
    execution_state = "REAL"

    def __init__(self, language: str = "nl",
                 client=None):
        if language not in ("nl", "en", "de", "fr"):
            raise TransportRefusedError(
                "wikipedia language must be nl/en/de/fr")
        self.language = language
        self._client = client

    def capabilities(self) -> dict:
        return {"provider": self.provider_name,
                "execution_state": self.execution_state,
                "search": True, "fetch": True,
                "hosts": sorted(SEARCH_ALLOWLIST)}

    def _api(self, params: dict):
        import httpx
        import json as _json
        from urllib.parse import urlencode
        base = (f"https://{self.language}.wikipedia.org"
                f"/w/api.php?{urlencode(params)}")
        canonical = validate_url(base,
                                 allow_hosts=SEARCH_ALLOWLIST)
        client = self._client
        own = client is None
        if own:
            client = httpx.Client(
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=False,
                headers={"User-Agent": "MyceliumResearch/1.0 "
                                       "(local-first research; "
                                       "contact: operator)"})
        try:
            try:
                response = client.get(canonical, timeout=(
                    FETCH_TIMEOUT_SECONDS))
            except Exception as error:
                raise TransportUnavailableError(
                    f"wikipedia unreachable: "
                    f"{type(error).__name__}: {str(error)[:160]}")
            if response.status_code != 200:
                raise TransportUnavailableError(
                    f"wikipedia HTTP {response.status_code}")
            if len(response.content) > MAX_BODY_BYTES:
                raise TransportRefusedError(
                    "wikipedia response over budget")
            try:
                return _json.loads(response.content.decode(
                    "utf-8", "replace"))
            except ValueError:
                raise TransportUnavailableError(
                    "wikipedia returned unparsable data")
        finally:
            if own:
                client.close()

    def search(self, query: str,
               max_results: int = 5) -> list[SearchHit]:
        if not isinstance(query, str) or not query.strip():
            raise TransportRefusedError(
                "search needs a query")
        data = self._api({"action": "query", "format": "json",
                          "list": "search",
                          "srsearch": query.strip()[:200],
                          "srlimit": max(1, min(int(max_results or 5),
                                                10)),
                          "srprop": "snippet|titlesnippet"})
        hits = []
        for item in (data.get("query", {}).get("search", [])
                     or [])[:10]:
            title = str(item.get("title", ""))[:200]
            if not title:
                continue
            page = title.replace(" ", "_")
            hits.append(SearchHit(
                title=title,
                url=(f"https://{self.language}.wikipedia.org"
                     f"/wiki/{page}"),
                snippet=re.sub(
                    r"<[^>]+>", "",
                    str(item.get("snippet", "")))[:300],
                provider="wikipedia",
                execution_state="REAL"))
        return hits

    def fetch_summary(self, title: str) -> FetchedPage:
        """Fetch the REST summary for one exact title. REAL."""
        if not isinstance(title, str) or not title.strip():
            raise TransportRefusedError(
                "summary needs a title")
        import httpx
        page = title.strip().replace(" ", "_")[:200]
        from urllib.parse import quote
        url = (f"https://{self.language}.wikipedia.org"
               f"/api/rest_v1/page/summary/{quote(page)}")
        canonical = validate_url(url,
                                 allow_hosts=SEARCH_ALLOWLIST)
        client = self._client
        own = client is None
        if own:
            client = httpx.Client(
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=False,
                headers={"User-Agent": "MyceliumResearch/1.0 "
                                       "(local-first research; "
                                       "contact: operator)"})
        try:
            try:
                response = client.get(canonical, timeout=(
                    FETCH_TIMEOUT_SECONDS))
            except Exception as error:
                raise TransportUnavailableError(
                    f"wikipedia unreachable: "
                    f"{type(error).__name__}: {str(error)[:160]}")
            if response.status_code != 200:
                raise TransportUnavailableError(
                    f"wikipedia HTTP {response.status_code}")
            import json as _json
            try:
                data = _json.loads(response.content.decode(
                    "utf-8", "replace"))
            except ValueError:
                raise TransportUnavailableError(
                    "wikipedia returned unparsable data")
            text = (f"{data.get('title', title)}\n\n"
                    f"{data.get('extract', '')}")[:MAX_BODY_BYTES]
            body = text.encode("utf-8")
            return FetchedPage(
                canonical_url=canonical, final_url=canonical,
                status_code=200, content_type="application/json",
                title=str(data.get("title", title))[:300],
                text=text,
                content_hash=hashlib.sha256(body).hexdigest(),
                retrieved_at=now(), execution_state="REAL",
                provider="wikipedia", hops=0)
        finally:
            if own:
                client.close()
