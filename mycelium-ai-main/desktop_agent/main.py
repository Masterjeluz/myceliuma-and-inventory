"""Standalone desktop-agent process (BIG #2).

Outbound only: registers as a worker node, heartbeats, claims the
next approved desktop action, revalidates approval, executes locally,
reports back. No inbound server, no port forwarding, no permanent
background action started from the coordinator.

Examples:

    python -m desktop_agent.main --coordinator http://127.0.0.1:8000
    python -m desktop_agent.main --once --max-steps 5
    python -m desktop_agent.main --read-only --dry-run
"""

import argparse
import logging
import signal

from coordinator.app.desktop_runtime import get_backend

from .agent import DEFAULT_MAX_STEPS, DEFAULT_POLL_SECONDS, DesktopAgent
from .identity import (
    FULL_CAPABILITIES,
    READONLY_CAPABILITIES,
    check_capabilities,
    stable_agent_id,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mycelium.desktop-agent")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mycelium desktop agent")
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--node-id", default=stable_agent_id())
    parser.add_argument("--capability", action="append", default=[],
                        help="Can be supplied more than once")
    parser.add_argument("--read-only", action="store_true",
                        help="Advertise observation only, never input")
    parser.add_argument("--tier", choices=["seed", "worker", "core"],
                        default="worker")
    parser.add_argument("--poll-seconds", type=float,
                        default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--once", action="store_true",
                        help="Single poll cycle, then exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate only; perform no input")
    return parser.parse_args()


def resolve_capabilities(config: argparse.Namespace) -> list[str]:
    if config.read_only:
        return list(READONLY_CAPABILITIES)
    if config.capability:
        return check_capabilities(config.capability)
    return list(FULL_CAPABILITIES)


def main(config: argparse.Namespace | None = None) -> int:
    config = config or arguments()
    try:
        capabilities = resolve_capabilities(config)
    except ValueError as error:
        logger.error("capabilities refused: %s", error)
        return 2
    if config.dry_run:
        import os
        os.environ["MYCELIUM_DESKTOP_DRYRUN"] = "1"
    agent = DesktopAgent(
        base_url=config.coordinator, node_id=config.node_id,
        capabilities=capabilities, backend=get_backend(),
        poll_seconds=config.poll_seconds, max_steps=config.max_steps,
        tier=config.tier)

    def handle_stop(signum, frame):
        logger.info("stop_requested signal=%s", signum)
        agent.stop()

    signal.signal(signal.SIGINT, handle_stop)
    try:
        signal.signal(signal.SIGTERM, handle_stop)
    except (OSError, ValueError):
        pass
    logger.info("desktop_agent_start node_id=%s capabilities=%s",
                agent.node_id, ",".join(capabilities))
    try:
        if config.once:
            agent.register()
            print(agent.run_once())
            return 0
        agent.run_forever()
    except Exception as error:
        logger.error("desktop_agent_failed cause=%s", error)
        return 1
    finally:
        agent.close()
    logger.info("desktop_agent_stop steps=%d", agent.steps_done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
