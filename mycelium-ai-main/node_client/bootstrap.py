"""One-command Linux node bootstrap (BIG #31).

Generates everything a fresh laptop needs — nothing is installed
or started by this script itself:

- python mycelium-node-join.py --coordinator URL --node-id NAME
  --token ...  →  prints the exact install + run commands
- --write-systemd               →  prints a systemd --user unit
- --check                       →  runs the coordinator pre-flight
  (linux_node.bootstrap_check) without registering anything

Pull-only, no inbound ports, no shell/RCE. Capabilities stay
allow-listed (linux_node.LINUX_CAPABILITIES); the token travels
via env/flag, never into a file written here.
"""

from __future__ import annotations

import argparse
import os as _os
import sys

sys.path.insert(0, _os.path.dirname(
    _os.path.dirname(_os.path.abspath(__file__))))


def build_run_command(*, repo_dir: str, coordinator: str, node_id: str,
                      tier: str = "worker",
                      capabilities: list[str] | None = None,
                      poll_seconds: int = 10) -> str:
    from coordinator.app.linux_node import check_capabilities
    caps = check_capabilities(list(capabilities or ["node.status"]))
    parts = [f"cd {repo_dir}",
             "python3 -m venv .venv",
             "source .venv/bin/activate",
             "pip install -e .",
             "export MYCELIUM_NODE_TOKEN=...",
             "python -m node_client.main "
             f"--coordinator {coordinator} "
             f"--node-id {node_id} --tier {tier} "
             + " ".join(f"--capability {cap}" for cap in caps)
             + f" --poll-seconds {poll_seconds}"]
    return "\n".join(parts)


def build_systemd_unit(*, repo_dir: str, coordinator: str, node_id: str,
                       tier: str = "worker",
                       capabilities: list[str] | None = None) -> str:
    from coordinator.app.linux_node import check_capabilities
    caps = check_capabilities(list(capabilities or ["node.status"]))
    cap_flags = " ".join(f"--capability {cap}" for cap in caps)
    return f"""[Unit]
Description=Mycelium node {node_id} (pull-only, user service)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={repo_dir}
Environment=MYCELIUM_NODE_TOKEN=%h/.config/mycelium/node-token
ExecStart={repo_dir}/.venv/bin/python -m node_client.main --coordinator {coordinator} --node-id {node_id} --tier {tier} {cap_flags} --poll-seconds 10
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mycelium Linux node one-command bootstrap")
    parser.add_argument("--coordinator",
                        default="http://127.0.0.1:8000")
    parser.add_argument("--node-id", default="linux-laptop-1")
    parser.add_argument("--tier", default="worker",
                        choices=["seed", "worker", "core"])
    parser.add_argument("--capability", action="append", default=[],
                        help="repeatable; starter set only")
    parser.add_argument("--token", default="",
                        help="only echoed as placeholder, never stored")
    parser.add_argument("--repo-dir", default="~/mycelium-ai-main")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--write-systemd", action="store_true",
                        help="print a systemd --user unit instead")
    parser.add_argument("--check", action="store_true",
                        help="run pre-flight checks only")
    return parser.parse_args()


def main() -> int:
    config = arguments()
    caps = config.capability or ["node.status"]
    if config.check:
        import json as _json
        import urllib.request
        payload = _json.dumps({
            "python_version": ".".join(
                str(part) for part in sys.version_info[:3]),
            "coordinator_url": config.coordinator,
            "node_id": config.node_id,
            "capabilities": caps}).encode()
        request = urllib.request.Request(
            config.coordinator.rstrip("/") +
            "/api/v1/linux-nodes/check", data=payload,
            headers={"Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(request,
                                        timeout=10) as response:
                print(_json.dumps(
                    _json.load(response), indent=1)[:2000])
        except Exception as error:
            print(f"pre-flight unreachable: {error}")
            print("Is the coordinator running? Start it first, "
                  "then re-run with --check.")
            return 1
        return 0
    if config.write_systemd:
        print(build_systemd_unit(
            repo_dir=config.repo_dir,
            coordinator=config.coordinator, node_id=config.node_id,
            tier=config.tier, capabilities=caps))
        print("# install: save as "
              "~/.config/systemd/user/mycelium-node.service, "
              "put the token in ~/.config/mycelium/node-token "
              "(chmod 600), then: systemctl --user daemon-reload && "
              "systemctl --user enable --now mycelium-node")
        return 0
    print("# 1. copy the repo to the laptop, then run:")
    print(build_run_command(
        repo_dir=config.repo_dir, coordinator=config.coordinator,
        node_id=config.node_id, tier=config.tier, capabilities=caps,
        poll_seconds=config.poll_seconds))
    print("# 2. replace export MYCELIUM_NODE_TOKEN=... with a real "
          "token (never commit it). First register binds it; "
          "later heartbeats must repeat it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
