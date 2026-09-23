#!/usr/bin/env bash
# Mycelium Linux node installer (P1).
#
# Usage:
#   ./scripts/install_linux_node.sh [--coordinator URL] [--node-id ID]
#       [--tier seed|worker|core] [--capability CAP]... [--poll-seconds N]
#       [--token ...] [--with-systemd] [--bootstrap]
#
# What it does (idempotent, safe to re-run):
#   1. checks OS / Python >= 3.11 / git (git fatal, rest advisory)
#   2. creates .venv when missing (never deletes anything)
#   3. installs the project (pip install -e .) incl. psutil for node_client
#   4. runs: python -m node_client.install install "$@" (writes local config,
#      preserves existing node identity, chmod 600, no network by default)
#
# What it never does: sudo, root services, inbound ports, secrets in output,
# Docker, cloud accounts. Outbound-only: the node polls the coordinator.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

say() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- 1. OS -----------------------------------------------------------------
if [ "$(uname -s)" != "Linux" ]; then
  die "this installer targets Linux (found: $(uname -s)). On Windows use the README PowerShell flow."
fi
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  say "OS: ${PRETTY_NAME:-${NAME:-Linux}} ($(uname -m))"
else
  say "OS: Linux ($(uname -m))"
fi

# --- 2. Python --------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found. Debian/Ubuntu: sudo apt update && sudo apt install -y python3 python3-venv git"
fi
PY_OK="$(python3 -c 'import sys; print("yes" if sys.version_info >= (3, 11) else "no")')"
if [ "$PY_OK" != "yes" ]; then
  die "Python >= 3.11 required (found: $(python3 --version 2>&1))."
fi
say "Python: $(python3 --version 2>&1) OK"

# --- 3. git (required to keep the checkout updated) --------------------------
if command -v git >/dev/null 2>&1; then
  say "Git: $(git --version) OK"
else
  die "git not found. Debian/Ubuntu: sudo apt install -y git"
fi

# --- 4. optional probes (never fatal) ----------------------------------------
if command -v ollama >/dev/null 2>&1; then
  say "Ollama: AVAILABLE (ollama-backed capabilities enabled)"
else
  say "Ollama: OPTIONAL / NOT FOUND (node still registers)"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  say "NVIDIA: AVAILABLE ($(nvidia-smi -L 2>/dev/null | head -n 1))"
else
  say "NVIDIA: OPTIONAL / NOT FOUND (CPU-only node)"
fi

# --- 5. venv (created once, reused afterwards) --------------------------------
if [ ! -f "$REPO_DIR/.venv/bin/python" ]; then
  say "creating .venv ..."
  python3 -m venv "$REPO_DIR/.venv" || die "python3 -m venv failed; Debian/Ubuntu: sudo apt install -y python3-venv"
else
  say ".venv: exists (reusing)"
fi
VENV_PY="$REPO_DIR/.venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1 || warn "pip upgrade failed, continuing"

# --- 6. project install (idempotent) ------------------------------------------
say "installing mycelium-ai into .venv ..."
"$VENV_PY" -m pip install -e "$REPO_DIR" || die "pip install -e . failed"
# node_client imports psutil (telemetry); keep it present even on minimal images.
if ! "$VENV_PY" -c "import psutil" >/dev/null 2>&1; then
  say "installing psutil (node telemetry) ..."
  "$VENV_PY" -m pip install "psutil>=5.9" || warn "psutil install failed; node telemetry will degrade"
fi

# --- 7. node config (the Python installer owns this; idempotent) --------------
say "configuring node ..."
"$VENV_PY" -m node_client.install install --repo-dir "$REPO_DIR" "$@"

say ""
say "done. Next:"
say "  - start:   .venv/bin/python -m node_client.main --coordinator <url> --node-id <id> --tier worker --poll-seconds 10"
say "             (exact command was printed above; token comes from the local config, never from output)"
say "  - check:   .venv/bin/python -m node_client.install doctor"
say "  - service: re-run with --with-systemd, then: systemctl --user daemon-reload && systemctl --user enable --now mycelium-node"
