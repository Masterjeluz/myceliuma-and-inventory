"""Mycelium developer notifier (BIG #33).

Small stdlib-only helper so a long OpenCode/BIG run can signal
Jelles without any external service or credential:

- `status`: one progress line on stdout, e.g.
  `BIG #33 [██████░░░░] Phase 4/10 — Implementing ecosystem`.
- `need`: LOUD approval-required signal: terminal bell (BEL),
  OSC 9 (Windows Terminal toast) + OSC 99 (WezTerm/iTerm
  notification), then the message.
- `done`: completion signal (bell + both OSC sequences).

How it works
------------
Terminal emulators listen for in-band escape sequences, so no
network, no account, no secret is involved:

- BEL (`\\a`) asks the terminal to flash/ring per the user's
  own terminal settings.
- `OSC 9 ; message ST` is the Windows Terminal toast escape
  (conhostbi/Windows Terminal show a notification).
- `OSC 99 ; message ST` is understood by WezTerm (and iTerm2
  variants) as a desktop notification.

If the terminal ignores them, the plain-text line still shows
in the OpenCode log — honest degradation, never a fake claim
of delivery. There is intentionally no sound file, no HTTP,
no push service here; web push stays UNAVAILABLE in-app.

Usage
-----
    python scripts/mycelium-notify.py status --big 33 --phase 4 \\
        --phases 10 --detail "Implementing ecosystem"
    python scripts/mycelium-notify.py need --message \\
        "Approval required: desktop action act_123"
    python scripts/mycelium-notify.py done --big 33

Exit code is always 0 unless arguments are invalid.
"""

from __future__ import annotations

import argparse
import sys

BEL = "\a"
ST = "\x1b\\"


def _osc(code: int, message: str) -> str:
    clean = " ".join(str(message or "").split())[:200]
    return f"\x1b]{code};{clean}{ST}"


def _out(line: str) -> None:
    """Console-safe write: UTF-8 where possible, ASCII fallback
    on legacy Windows code pages (never crash the caller)."""
    try:
        sys.stdout.write(line + "\n")
    except UnicodeEncodeError:
        ascii_line = line.replace("█", "#").replace("░", "-")
        ascii_line = ascii_line.encode("ascii",
                                       "replace").decode("ascii")
        sys.stdout.write(ascii_line + "\n")
    sys.stdout.flush()


def progress_bar(done: int, total: int, width: int = 10) -> str:
    total = max(1, total)
    done = max(0, min(done, total))
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)


def cmd_status(args: argparse.Namespace) -> int:
    bar = progress_bar(args.phase, args.phases)
    line = (f"BIG #{args.big} [{bar}] Phase "
            f"{args.phase}/{args.phases}")
    if args.detail:
        line += f" — {args.detail[:120]}"
    _out(line)
    return 0


def _alert(message: str, loud: bool) -> int:
    _out(message)
    try:
        sys.stdout.write(BEL)
        # Windows Terminal toast + WezTerm/desktop notification.
        sys.stdout.write(_osc(9, message))
        sys.stdout.write(_osc(99, message))
        if loud:
            sys.stdout.write(BEL)
    except UnicodeEncodeError:
        pass
    sys.stdout.flush()
    return 0


def cmd_need(args: argparse.Namespace) -> int:
    return _alert(f"🔔 APPROVAL REQUIRED — {args.message}", True)


def cmd_done(args: argparse.Namespace) -> int:
    return _alert(f"🌱 BIG #{args.big} complete — "
                  f"{args.message or 'check the report'}", False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mycelium terminal progress + notification helper")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="print a progress line")
    status.add_argument("--big", type=int, required=True)
    status.add_argument("--phase", type=int, required=True)
    status.add_argument("--phases", type=int, required=True)
    status.add_argument("--detail", default="")
    status.set_defaults(func=cmd_status)
    need = sub.add_parser("need",
                          help="loud approval-required signal")
    need.add_argument("--message", required=True)
    need.set_defaults(func=cmd_need)
    done = sub.add_parser("done", help="completion signal")
    done.add_argument("--big", type=int, required=True)
    done.add_argument("--message", default="")
    done.set_defaults(func=cmd_done)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
