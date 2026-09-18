import argparse
import asyncio
import logging
import os
import platform
import socket
import uuid

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mycelium.node")


def detected_memory_mb() -> int:
    """Return local physical memory without adding a dependency to small nodes."""
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_extended_virtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.total_phys // (1024 * 1024)
        except (AttributeError, OSError):
            return 0
    try:
        return (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) // (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        return 0


FETCH_MAX_CHARS = 65536
FETCH_TIMEOUT_SECONDS = 20.0
FETCH_ALLOWED_CONTENT = ("text/", "application/json",
                         "application/xml")


def _fetch_host_blocked(host: str) -> bool:
    """Local numeric/host check on the node. The coordinator
    validates every URL fully first (research_transport); this is
    defense in depth for the bytes this host actually opens."""
    import ipaddress as _ip
    cleaned = (host or "").lower().rstrip(".")
    if not cleaned:
        return True
    try:
        parsed = _ip.ip_address(cleaned)
        return (parsed.is_private or parsed.is_loopback
                or parsed.is_link_local or parsed.is_multicast
                or parsed.is_reserved or parsed.is_unspecified)
    except ValueError:
        pass
    if cleaned in ("localhost",):
        return True
    if all(part.isdigit() and 0 <= int(part) <= 255
           for part in cleaned.split(".") if part) and \
            "." in cleaned:
        return True
    return False


async def fetch_url_narrow_async(
        url: str, max_chars: int = FETCH_MAX_CHARS
        ) -> tuple[bool, dict, str | None]:
    """Async variant for tests. Same guards as the sync path."""
    checked = _check_fetch_url(url, max_chars)
    if isinstance(checked, str):
        return False, {}, checked
    text, cap = checked
    try:
        async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=False) as client:
            response = await client.get(
                text, headers={"User-Agent": "MyceliumNode/1 "
                                            "(research fetch)"})
    except Exception as error:
        return False, {}, f"fetch failed: {error}"
    return _fetch_result(response, text, cap)


def _check_fetch_url(url: str, max_chars: int
                     ) -> tuple[str, int] | str:
    """Shared URL guards. Returns (url, cap) or an error string."""
    from urllib.parse import urlparse as _urlparse
    if not isinstance(url, str) or not url.strip():
        return "fetch needs a URL"
    text = url.strip()
    if len(text) > 2000:
        return "URL too long; refusing"
    try:
        parsed = _urlparse(text)
    except ValueError as error:
        return f"URL unparsable: {error}"
    if parsed.scheme.lower() not in ("https", "http"):
        return "https/http URLs only; refusing"
    if not parsed.hostname or _fetch_host_blocked(
            parsed.hostname):
        return "host refused (local/numeric/empty)"
    if "@" in text.split("://", 1)[1].split("/", 1)[0]:
        return "credentials in URLs are refused"
    try:
        cap = max(1024, min(int(max_chars or FETCH_MAX_CHARS),
                            FETCH_MAX_CHARS))
    except (TypeError, ValueError):
        return "max_chars must be an integer"
    return text, cap


def _fetch_result(response, text: str, cap: int
                  ) -> tuple[bool, dict, str | None]:
    """Shared bounded response handling. No redirects, text only."""
    if response.status_code in (301, 302, 303, 307, 308):
        return False, {}, "redirects are never followed; refusing"
    if not 200 <= response.status_code < 300:
        return False, {}, f"HTTP {response.status_code}; refusing"
    content_type = response.headers.get("content-type", "").lower()
    if content_type and not content_type.startswith(
            FETCH_ALLOWED_CONTENT):
        return False, {}, (f"content-type '{content_type}' refused; "
                            "text only")
    body = response.content[:cap + 1]
    truncated = len(body) > cap
    decoded = body[:cap].decode("utf-8", errors="replace")
    return True, {"url": text, "status_code": response.status_code,
                  "content_type": content_type[:120],
                  "text": decoded, "truncated": truncated,
                  "chars": len(decoded)}, None


def fetch_url_narrow(url: str, max_chars: int = FETCH_MAX_CHARS
                     ) -> tuple[bool, dict, str | None]:
    """Fetch one coordinator-approved URL as bounded text (sync,
    for the claim loop). No redirects, no credentials, no
    binaries, no shell — bytes in, text out."""
    checked = _check_fetch_url(url, max_chars)
    if isinstance(checked, str):
        return False, {}, checked
    text, cap = checked
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS,
                          follow_redirects=False) as client:
            response = client.get(
                text, headers={"User-Agent": "MyceliumNode/1 "
                                            "(research fetch)"})
    except Exception as error:
        return False, {}, f"fetch failed: {error}"
    return _fetch_result(response, text, cap)


def execute_safe_task(task: dict[str, object]) -> tuple[bool, dict[str, object], str | None]:
    """Execute only allow-listed, non-invasive local tasks.

    This function is intentionally small: task payloads never become commands,
    paths or Python code. New executors need their own explicit review.

    The claim loop auto-executes, so it may only serve read-only kinds:
    system_inventory, desktop_screenshot and research.fetch_url.
    Desktop INPUT (click, type, key presses, ...) is never
    auto-executed here: those actions run exclusively in the local
    desktop runtime after explicit human approval (see
    coordinator/app/agent_loop.py). A node that claims input tasks
    receives a refusal, never silent execution.
    """
    if task["kind"] == "research.fetch_url":
        payload = task.get("payload", {})
        if not isinstance(payload, dict):
            return False, {}, "fetch payload must be an object"
        return fetch_url_narrow(
            str(payload.get("url", "")),
            int(payload.get("max_chars", FETCH_MAX_CHARS))
            if str(payload.get("max_chars", "")).strip().isdigit()
            else FETCH_MAX_CHARS)
    if task["kind"] == "system_inventory":
        return True, {
            "operating_system": platform.system(),
            "machine": platform.machine(),
            "cpu_cores": os.cpu_count() or 1,
            "memory_mb": detected_memory_mb(),
        }, None
    if task["kind"] == "desktop_screenshot":
        try:
            from coordinator.app.desktop_runtime import get_backend
        except ImportError as error:
            return False, {}, f"Screenshot backend unavailable: {error}"
        try:
            observation = get_backend().screenshot()
        except Exception as error:
            return False, {}, f"Screenshot refused: {error}"
        return True, observation.model_dump(mode="json"), None
    if str(task["kind"]).startswith("desktop_"):
        return False, {}, (
            f"Desktop input '{task['kind']}' needs explicit human approval "
            "and never auto-executes in the claim loop; refusing")
    return False, {}, f"No safe executor installed for task kind: {task['kind']}"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight Mycelium AI node")
    parser.add_argument("--coordinator", default="http://localhost:8000")
    parser.add_argument("--node-id", default=f"node-{uuid.getnode():x}")
    parser.add_argument("--tier", choices=["seed", "worker", "core"], default="seed")
    parser.add_argument("--capability", action="append", default=[], help="Can be supplied more than once")
    parser.add_argument("--energy-source", default="unknown", help="For example solar, grid or battery")
    parser.add_argument("--node-token", default=None,
                        help="Node credential (or MYCELIUM_NODE_TOKEN); bound on first register, required afterwards")
    parser.add_argument("--executor", action="append", default=[], help="Executor to advertise, exec:<kind>; can be supplied more than once")
    parser.add_argument("--model", action="append", default=[], help="Model to advertise as model_id:type, e.g. model:sim-vlm:vlm; can be supplied more than once")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    return parser.parse_args()


def node_token_from(config: argparse.Namespace) -> str | None:
    token = config.node_token or os.environ.get("MYCELIUM_NODE_TOKEN", "")
    return token.strip() or None


def advertised_models(specs: list[str]) -> list[dict]:
    """Parse --model model_id:type entries. Fail fast on bad input."""
    models = []
    for spec in specs or []:
        if ":" not in spec:
            raise ValueError(f"Model spec '{spec}' must be model_id:type")
        model_id, _, model_type = spec.rpartition(":")
        models.append({"model_id": model_id.strip(),
                       "display_name": model_id.strip(),
                       "model_type": model_type.strip() or "other",
                       "capabilities": [],
                       "provider": "local",
                       "status": "available"})
    return models


async def run(config: argparse.Namespace) -> None:
    base_url = config.coordinator.rstrip("/") + "/api/v1"
    token = node_token_from(config)
    registration = {"node_id": config.node_id, "hostname": socket.gethostname(), "tier": config.tier,
                    "capabilities": config.capability, "cpu_cores": os.cpu_count() or 1,
                    "memory_mb": detected_memory_mb(), "energy_source": config.energy_source,
                    "executors": config.executor, "models": advertised_models(config.model)}
    if token:
        registration["node_token"] = token
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{base_url}/nodes/register", json=registration)
        response.raise_for_status()
        logger.info("registered %s on %s (%s)", config.node_id, platform.system(), config.tier)
        while True:
            try:
                heartbeat = {"available": True}
                if token:
                    heartbeat["node_token"] = token
                await client.post(f"{base_url}/nodes/{config.node_id}/heartbeat", json=heartbeat)
                claim_url = f"{base_url}/tasks/claim/{config.node_id}"
                if token:
                    from urllib.parse import quote
                    claim_url += f"?node_token={quote(token, safe='')}"
                response = await client.post(claim_url)
                response.raise_for_status()
                task = response.json()
                if task:
                    logger.info("received task %s (%s)", task["id"], task["kind"])
                    success, result, error = execute_safe_task(task)
                    completion = await client.post(f"{base_url}/tasks/{task['id']}/complete", json={
                        "success": success, "result": result, "error": error,
                    })
                    completion.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("coordinator unavailable: %s", error)
            await asyncio.sleep(config.poll_seconds)


if __name__ == "__main__":
    asyncio.run(run(arguments()))
