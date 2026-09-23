"""Mycelium OpenCode worker: register -> heartbeat -> claim task ->
fetch context -> run OpenCode locally -> complete -> poll again.

Executor, never authority. This worker only ever talks to the
coordinator through an explicit endpoint allow-list (read task
queue state, claim its own work, report its own results). It never
calls approval, write-approval, physical-execution, verification,
desktop-dispatch or task-creation endpoints: human YES, fingerprint
and safety gates stay fully owned by the existing backend routes.
Task payloads are goal descriptions, never commands: payload strings
are never executed as shell, never used as paths, and never become
Python code. Local OpenCode runs without --auto, so its own
permission system stays in charge on the worker machine.
"""

import argparse
import asyncio
import logging
import os
import re
import socket
import subprocess
import uuid

import httpx

logger = logging.getLogger("code_worker")

NODE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")

DEFAULT_CAPABILITIES = ["code.patch", "code.review", "code.test"]
DEFAULT_EXECUTORS = ["exec:code"]

# Explicit OpenCode model for every local run. Operator configuration
# only (--opencode-model); task payloads never select the model.
DEFAULT_OPENCODE_MODEL = "opencode/muse-spark-1.3-contributor-free"

ALLOWED_KIND_PREFIXES = ("code.",)

# (method, path rule): path rule is either an exact prefix that must
# match fully, or a (prefix, suffix) pair. Anything else is refused
# BEFORE any network I/O, so this module cannot approve, write,
# execute physically, verify, dispatch desktop actions, or create
# tasks even if a task payload asked for it.
ALLOWED_CALLS = (
    ("POST", "/api/v1/nodes/register", None),
    ("POST", "/api/v1/nodes/", "/heartbeat"),
    ("POST", "/api/v1/tasks/claim/", None),
    ("POST", "/api/v1/tasks/", "/complete"),
    ("GET", "/api/v1/context/packet", None),
    ("GET", "/api/v1/project/package", None),
    ("GET", "/api/v1/missions/", None),
    ("GET", "/api/v1/tasks", None),
    ("GET", "/api/v1/presence", None),
    ("GET", "/api/v1/guide", None),
)


class WorkerRefusedError(ValueError):
    """Local policy refused an action; nothing was sent or run."""


def check_call(method: str, path: str) -> str:
    """Fail-closed endpoint gate. Returns the path when allowed."""
    clean = str(path or "").split("?", 1)[0]
    for allowed_method, prefix, suffix in ALLOWED_CALLS:
        if str(method or "").upper() != allowed_method:
            continue
        if not clean.startswith(prefix):
            continue
        if suffix is not None and not clean.endswith(suffix):
            continue
        if prefix == "/api/v1/tasks" and suffix is None:
            continue  # GET list only; POST create must match /complete
        return clean
    raise WorkerRefusedError(
        f"Worker never calls {method} {clean}; refusing")


def check_node_id(node_id: str) -> str:
    """Same identity alphabet as the coordinator registration."""
    cleaned = str(node_id or "").strip()[:80]
    if not cleaned or not NODE_ID_PATTERN.match(cleaned):
        raise WorkerRefusedError(
            "node_id must match ^[a-zA-Z0-9._-]+$")
    return cleaned


MODEL_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._:-]+$")


def check_model(model: str) -> str:
    """Operator-configured model id only, `provider/name` shape.
    Task payloads never reach this function; anything else is
    refused BEFORE any OpenCode run, so the effective model stays
    explicit and deterministic."""
    cleaned = str(model or "").strip()[:200]
    if not cleaned or not MODEL_PATTERN.match(cleaned):
        raise WorkerRefusedError(
            "opencode model must look like provider/name")
    return cleaned


def default_node_id() -> str:
    """opencode-<host>, sanitized into the coordinator alphabet."""
    host = re.sub(r"[^a-zA-Z0-9._-]", "-",
                  socket.gethostname() or "host").strip(".-")
    return check_node_id(f"opencode-{host or 'host'}")


def node_token_from(config: argparse.Namespace) -> str | None:
    """Local credential only: CLI flag or MYCELIUM_NODE_TOKEN env.
    Never hardcoded, never sent anywhere except the coordinator
    register/heartbeat/claim calls over the configured base URL."""
    token = config.node_token or os.environ.get(
        "MYCELIUM_NODE_TOKEN", "")
    return token.strip() or None


async def api_call(client: httpx.AsyncClient, method: str,
                   url: str, json: dict | None = None):
    """Single gated HTTP call. Policy first, network second."""
    from urllib.parse import urlsplit
    check_call(method, urlsplit(url).path)
    if method.upper() == "GET":
        response = await client.get(url)
    else:
        response = await client.post(url, json=json or {})
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


async def register(client: httpx.AsyncClient, base_url: str,
                   registration: dict) -> None:
    await api_call(client, "POST",
                   f"{base_url}/nodes/register",
                   json=registration)


async def send_heartbeat(client: httpx.AsyncClient, base_url: str,
                         node_id: str, token: str | None) -> None:
    heartbeat: dict = {"available": True}
    if token:
        heartbeat["node_token"] = token
    await api_call(client, "POST",
                   f"{base_url}/nodes/{node_id}/heartbeat",
                   json=heartbeat)


async def claim_task(client: httpx.AsyncClient, base_url: str,
                     node_id: str, token: str | None) -> dict | None:
    url = f"{base_url}/tasks/claim/{node_id}"
    if token:
        from urllib.parse import quote
        url += f"?node_token={quote(token, safe='')}"
    return await api_call(client, "POST", url)


async def fetch_context(client: httpx.AsyncClient, base_url: str,
                        goal: str,
                        conversation_id: str = "") -> dict:
    from urllib.parse import quote
    url = f"{base_url}/context/packet?goal={quote(goal[:500])}"
    scope = str(conversation_id or "").strip()[:80]
    if scope:
        url += f"&conversation_id={quote(scope, safe='')}"
    return await api_call(client, "GET", url) or {}


async def fetch_package(client: httpx.AsyncClient, base_url: str,
                        goal: str,
                        conversation_id: str = "") -> dict:
    """Bounded project package (server caps; never file contents,
    never secrets, never permissions). Best-effort: callers proceed
    without it rather than refusing work over context."""
    from urllib.parse import quote
    url = f"{base_url}/project/package?q={quote(goal[:200])}"
    scope = str(conversation_id or "").strip()[:80]
    if scope:
        url += f"&conversation_id={quote(scope, safe='')}"
    return await api_call(client, "GET", url) or {}


async def fetch_mission_conversation(client: httpx.AsyncClient,
                                     base_url: str,
                                     mission_id: str) -> str:
    """conversation_id for a claimed mission, or "". Read-only,
    fail-soft: unknown missions simply yield no extra scope."""
    cleaned = str(mission_id or "").strip()[:80]
    if not cleaned:
        return ""
    from urllib.parse import quote
    try:
        mission = await api_call(
            client, "GET",
            f"{base_url}/missions/{quote(cleaned, safe='')}")
    except WorkerRefusedError:
        return ""
    except Exception:
        return ""
    if not isinstance(mission, dict):
        return ""
    return str(mission.get("conversation_id", "") or "").strip()[:80]


CONTEXT_CHAR_BUDGET = 1500


def render_task_context(packet: dict | None,
                        package: dict | None,
                        budget: int = CONTEXT_CHAR_BUDGET) -> str:
    """Render worker prompt context from allow-listed metadata only.

    Picks: package summary, packet constraints, open missions and
    research titles. Unknown keys, health content, file contents and
    anything secret-shaped never reach the prompt: only these four
    capped fields are read, everything else is dropped, and the
    total is truncated to budget. Pure function, no I/O.
    """
    lines: list[str] = []

    def _text(value) -> str:
        return str(value or "").strip()

    if isinstance(package, dict):
        summary = _text(package.get("summary"))[:600]
        if summary:
            lines.append(summary)
    if isinstance(packet, dict):
        constraints = packet.get("constraints")
        if isinstance(constraints, list):
            for entry in constraints[:5]:
                text = _text(entry)[:200]
                if text:
                    lines.append(f"- {text}")
        missions = packet.get("open_missions")
        if isinstance(missions, list):
            for entry in missions[:3]:
                if not isinstance(entry, dict):
                    continue
                text = (f"{_text(entry.get('id'))[:40]} "
                        f"{_text(entry.get('goal'))[:120]} "
                        f"[{_text(entry.get('status'))[:20]}]").strip()
                if text.strip("[] "):
                    lines.append(f"- {text}")
        research = packet.get("research")
        if isinstance(research, list):
            for entry in research[:3]:
                if not isinstance(entry, dict):
                    continue
                text = _text(entry.get("title"))[:120]
                if text:
                    lines.append(f"- research: {text}")
    rendered = "\n".join(lines).strip()
    return rendered[:max(1, int(budget or CONTEXT_CHAR_BUDGET))]


async def complete_task(client: httpx.AsyncClient, base_url: str,
                        task_id: int, node_id: str, success: bool,
                        result: dict | None = None,
                        error: str | None = None) -> None:
    body: dict = {"success": bool(success),
                  "result": dict(result or {}),
                  "error": (str(error or "")[:2000] if error
                            else None),
                  "node_id": node_id}
    await api_call(client, "POST",
                   f"{base_url}/tasks/{task_id}/complete",
                   json=body)


def git_changed_files(workdir: str) -> list[str]:
    """Read-only git status scan for the result report."""
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=workdir, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    files = []
    for entry in completed.stdout.split(b"\0"):
        text = entry.decode("utf-8", "replace").strip()
        if len(text) > 3:
            files.append(text[3:][:200])
    return sorted(set(files))[:50]


def build_opencode_argv(binary: str, prompt: str,
                          workdir: str,
                          model: str = DEFAULT_OPENCODE_MODEL,
                          platform_name: str | None = None,
                          comspec: str | None = None) -> list[str]:
    """Argv for one local OpenCode run, list form (never shell).

    The model is always passed explicitly with -m, so the run never
    depends on OpenCode's implicit default. The model is operator
    configuration (--opencode-model); task payloads never select it.

    On Windows a .cmd/.bat binary cannot start directly from
    CreateProcess, so it is launched explicitly through COMSPEC
    (`cmd /d /c`). The binary itself stays operator configuration
    (--opencode-bin); task payloads never select the executable.
    """
    argv = [binary, "run", prompt[:4000], "-m", check_model(model),
            "--format", "json", "--dir", target(workdir)]
    system = platform_name if platform_name is not None else os.name
    if system == "nt" and binary.lower().endswith((".cmd", ".bat")):
        shell = (comspec if comspec is not None
                 else os.environ.get("COMSPEC", ""))
        if not str(shell or "").strip():
            raise WorkerRefusedError(
                "COMSPEC is not set; refusing to guess the shell")
        return [shell, "/d", "/c"] + argv
    return argv


def target(workdir: str) -> str:
    """Validated local folder OpenCode runs in."""
    cleaned = str(workdir or "").strip()
    if not cleaned or not os.path.isdir(cleaned):
        raise WorkerRefusedError("workdir must be a local folder")
    return cleaned


def run_opencode(prompt: str, workdir: str,
                 binary: str = "opencode",
                 model: str = DEFAULT_OPENCODE_MODEL,
                 timeout_seconds: int = 240) -> tuple[bool, str]:
    """Run local OpenCode once, non-interactively.

    Never passes --auto: the local OpenCode permission system stays
    in charge. Returns (ok, combined_output). Raises on transport
    failure so the caller reports failed, never fake success.
    """
    if not str(prompt or "").strip():
        raise WorkerRefusedError("OpenCode prompt must be text")
    folder = target(workdir)
    argv = build_opencode_argv(binary, prompt, folder, model=model)
    try:
        completed = subprocess.run(
            argv, capture_output=True, timeout=int(timeout_seconds))
    except FileNotFoundError as error:
        raise WorkerRefusedError(
            f"OpenCode binary not found: {binary}") from error
    except subprocess.TimeoutExpired as error:
        raise WorkerRefusedError(
            f"OpenCode timed out after {timeout_seconds}s") from error
    output = (completed.stdout.decode("utf-8", "replace")
              + completed.stderr.decode("utf-8", "replace"))[-4000:]
    return completed.returncode == 0, output


def run_tests(command: str, workdir: str,
              timeout_seconds: int = 600) -> tuple[bool, str]:
    """Run the worker's FIXED local test command (never from the
    task payload: payload strings never become commands). Empty
    command means no tests; reported honestly as skipped."""
    if not str(command or "").strip():
        return True, "skipped: no --test-cmd configured"
    import shlex
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as error:
        return False, f"test command refused: {error}"
    if not argv:
        return True, "skipped: no --test-cmd configured"
    try:
        completed = subprocess.run(
            argv, cwd=workdir, capture_output=True,
            timeout=int(timeout_seconds))
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"test run failed: {error}"[:1000]
    output = (completed.stdout.decode("utf-8", "replace")
              + completed.stderr.decode("utf-8", "replace"))[-2000:]
    return completed.returncode == 0, output


def check_task_kind(kind: str) -> str:
    """Only explicitly allowed kinds execute. Everything else is
    reported as failed/unsupported, never run silently."""
    cleaned = str(kind or "").strip()
    if any(cleaned.startswith(prefix)
           for prefix in ALLOWED_KIND_PREFIXES):
        return cleaned
    raise WorkerRefusedError(
        f"Task kind '{cleaned}' is not an allowed worker kind "
        f"(allowed prefixes: {list(ALLOWED_KIND_PREFIXES)}); "
        "refusing instead of executing")


def execute_code_task(task: dict, workdir: str,
                      opencode_binary: str = "opencode",
                      opencode_model: str = DEFAULT_OPENCODE_MODEL,
                      test_command: str = "",
                      context: str = "",
                      runner=run_opencode) -> tuple[bool, dict, str | None]:
    """Execute one claimed task. Returns (success, result, error)
    in exactly the coordinator complete-contract shape."""
    try:
        kind = check_task_kind(str(task.get("kind", "")))
    except WorkerRefusedError as error:
        return False, {}, str(error)
    payload = task.get("payload", {})
    if not isinstance(payload, dict):
        return False, {}, "task payload must be an object"
    goal = str(payload.get("goal", "") or "").strip()
    if not goal:
        return False, {}, "task has no goal; nothing to do"
    prompt = (f"Mycelium task #{task.get('id')} "
              f"({kind}): {goal}".strip())
    section = str(context or "").strip()[:CONTEXT_CHAR_BUDGET]
    if section:
        prompt = (f"{prompt}\n\nProject context (read-only, "
                  f"bounded):\n{section}")
    before = set(git_changed_files(workdir))
    try:
        ok, output = runner(prompt, workdir,
                            binary=opencode_binary,
                            model=check_model(opencode_model))
    except WorkerRefusedError as error:
        return False, {}, str(error)
    except Exception as error:
        return False, {}, f"OpenCode run failed: {error}"[:1000]
    after = set(git_changed_files(workdir))
    tests_ok, tests_output = run_tests(test_command, workdir)
    summary = (f"OpenCode {kind} finished "
               f"({'ok' if ok else 'non-zero exit'}); "
               f"tests {'passed' if tests_ok else 'failed'}; "
               f"{len(after - before)} file(s) changed.")
    result = {"files_changed": sorted(after - before)[:50],
              "tests": [{"command": test_command or "skipped",
                         "passed": tests_ok,
                         "output": tests_output[:2000]}],
              "summary": summary[:1000],
              "opencode_output": output[-2000:]}
    if not ok:
        return False, result, "OpenCode exited non-zero"
    if not tests_ok and test_command.strip():
        return False, result, "local tests failed"
    return True, result, None


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mycelium OpenCode worker (executor, not authority)")
    parser.add_argument("--coordinator",
                        default="http://localhost:8000")
    parser.add_argument("--node-id", default=None,
                        help="Defaults to opencode-<hostname>")
    parser.add_argument("--tier", choices=["seed", "worker", "core"],
                        default="worker")
    parser.add_argument("--capability", action="append",
                        default=[],
                        help="Can be supplied more than once")
    parser.add_argument("--executor", action="append", default=[],
                        help="Executors to advertise, exec:<kind>")
    parser.add_argument("--node-token", default=None,
                        help="Node credential (or MYCELIUM_NODE_TOKEN)")
    parser.add_argument("--workdir", default=os.getcwd(),
                        help="Local folder OpenCode runs in")
    parser.add_argument("--opencode-bin", default="opencode",
                        help="Local OpenCode binary")
    parser.add_argument("--opencode-model",
                        default=DEFAULT_OPENCODE_MODEL,
                        help="Explicit OpenCode model (provider/name)")
    parser.add_argument("--test-cmd", default="",
                        help="Fixed local test command (never from payload)")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--once", action="store_true",
                        help="Single poll iteration, then exit")
    return parser.parse_args()


async def run_once(client: httpx.AsyncClient, base_url: str,
                   node_id: str, token: str | None,
                   workdir: str, opencode_binary: str,
                   test_command: str,
                   opencode_model: str = DEFAULT_OPENCODE_MODEL,
                   runner=run_opencode) -> str:
    """One poll iteration: heartbeat, claim, context, execute,
    complete. Returns a short status word for logs."""
    await send_heartbeat(client, base_url, node_id, token)
    task = await claim_task(client, base_url, node_id, token)
    if not task:
        return "idle"
    goal = ""
    try:
        payload = task.get("payload", {})
        if isinstance(payload, dict):
            goal = str(payload.get("goal", "") or "")
        conversation_id = ""
        try:
            mission_id = task.get("mission_id", "")
            if isinstance(mission_id, str) and mission_id.strip():
                conversation_id = await fetch_mission_conversation(
                    client, base_url, mission_id)
        except Exception:
            conversation_id = ""
        packet: dict = {}
        package: dict = {}
        try:
            packet = await fetch_context(
                client, base_url, goal or str(task.get(
                    "kind", "")),
                conversation_id=conversation_id)
        except Exception:
            packet = {}
        try:
            package = await fetch_package(
                client, base_url, goal or str(task.get(
                    "kind", "")),
                conversation_id=conversation_id)
        except Exception:
            package = {}
        context = render_task_context(packet, package)
        success, result, error = execute_code_task(
            {"kind": task.get("kind"), "payload": payload,
             "mission_id": task.get("mission_id")},
            workdir, opencode_binary=opencode_binary,
            opencode_model=opencode_model,
            test_command=test_command, context=context,
            runner=runner)
    except WorkerRefusedError as error:
        success, result, error = False, {}, str(error)
    except Exception as error:
        success, result, error = (
            False, {}, f"worker error: {error}"[:1000])
    await complete_task(client, base_url, int(task.get("id")),
                        node_id, success, result, error)
    return "completed" if success else "failed"


async def run(config: argparse.Namespace) -> None:
    base_url = config.coordinator.rstrip("/") + "/api/v1"
    token = node_token_from(config)
    node_id = check_node_id(config.node_id or default_node_id())
    capabilities = list(config.capability or DEFAULT_CAPABILITIES)
    executors = list(config.executor or DEFAULT_EXECUTORS)
    registration = {"node_id": node_id,
                    "hostname": socket.gethostname(),
                    "tier": config.tier,
                    "capabilities": capabilities,
                    "executors": executors}
    if token:
        registration["node_token"] = token
    async with httpx.AsyncClient(timeout=10) as client:
        await register(client, base_url, registration)
        logger.info("code worker %s registered (%s)",
                    node_id, config.tier)
        while True:
            try:
                status = await run_once(
                    client, base_url, node_id, token,
                    str(config.workdir),
                    str(config.opencode_bin),
                    str(config.test_cmd or ""),
                    opencode_model=str(config.opencode_model))
                logger.info("poll: %s", status)
            except httpx.HTTPError as error:
                logger.warning("coordinator unavailable: %s", error)
            if config.once:
                return
            await asyncio.sleep(config.poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(arguments()))
