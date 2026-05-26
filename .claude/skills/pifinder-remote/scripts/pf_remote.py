#!/usr/bin/env python3
"""pf_remote.py — launch and drive a headless PiFinder over its HTTP API.

This is the single entry point for the pifinder-remote skill. It needs only the
Python standard library, so it runs under any python3 (it does not need to be
the PiFinder venv interpreter — it locates and uses that itself when launching).

Subcommands
-----------
  launch     Start cedar-detect-server + a headless PiFinder, wait until the
             web API answers, and record PIDs/process-groups to a state file.
  ready      Poll until the API answers (or time out).
  screen     Fetch GET /api/screen and save the 128x128 PNG.
  key        POST one or more buttons to /api/key, in order, with a small delay.
  status     GET /api/status (aggregated state) and print it.
  solution   GET /api/solution (plate-solve result) and print it.
  location   GET /api/location and print it.
  get        GET an arbitrary /api/* path and print the body.
  stop       Graceful shutdown via POST /api/stop, then escalate to
             SIGTERM/SIGKILL on the process group if anything lingers, and
             stop cedar-detect-server too.
  kill       Skip the graceful step; force-kill the recorded process groups.
  logs       Print the tail of the PiFinder / cedar log files.

Why a process group, not just a PID
------------------------------------
PiFinder is multi-process. Its children run bare ``while True`` loops, are not
daemonized, and do not watch a stop flag — the only thing that brings them down
cleanly is SIGINT delivered to the whole group at once (what a terminal Ctrl-C
does). ``launch`` therefore starts PiFinder in its own session
(``start_new_session=True``) so the whole tree shares one process group that is
isolated from this launcher. ``/api/stop`` signals that group from the inside;
``stop`` here escalates from the outside if a child still stalls. See
SKILL.md for the full rationale.
"""

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_PATH = Path(tempfile.gettempdir()) / "pf_remote_state.json"
LOG_DIR = Path(tempfile.gettempdir())
PIFINDER_LOG = LOG_DIR / "pf_remote_pifinder.log"
CEDAR_LOG = LOG_DIR / "pf_remote_cedar.log"

DEFAULT_PORT = 8080
CEDAR_PORT = 50551


# ─────────────────────────── discovery ───────────────────────────


def find_repo(explicit=None):
    """Locate the PiFinder repo root (the dir holding python/PiFinder/main.py)."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("PIFINDER_REPO"):
        candidates.append(Path(os.environ["PIFINDER_REPO"]))
    # This skill is project-scoped, so the repo root is normally a few levels up
    # from the script. Also walk up from the script and the cwd as a fallback.
    here = Path(__file__).resolve()
    candidates.extend(here.parents)
    candidates.extend(Path.cwd().resolve().parents)
    candidates.append(Path.cwd().resolve())
    seen = set()
    for c in candidates:
        c = c.resolve()
        if c in seen:
            continue
        seen.add(c)
        if (c / "python" / "PiFinder" / "main.py").exists():
            return c
    raise SystemExit(
        "Could not find the PiFinder repo (no python/PiFinder/main.py). "
        "Pass --repo /path/to/PiFinder or set PIFINDER_REPO."
    )


def find_python(repo):
    """Return the PiFinder venv interpreter if present, else this interpreter."""
    for rel in (
        "python/venv/bin/python",
        "python/.venv/bin/python",
        ".venv/bin/python",
        "venv/bin/python",
    ):
        p = repo / rel
        if p.exists():
            return str(p)
    return sys.executable


def find_cedar(repo):
    """Pick the cedar-detect-server binary matching this OS/arch."""
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "darwin":
        prefer = ["arm64"] if machine in ("arm64", "aarch64") else ["x86_64", "amd64", "x86"]
    else:  # assume linux
        prefer = ["aarch64", "arm64"] if machine in ("aarch64", "arm64") else ["x86_64", "amd64", "x86"]
    files = sorted((repo / "bin").glob("cedar-detect-server*"))
    for suffix in prefer:
        for f in files:
            if f.name.endswith(suffix):
                return f
    for f in files:  # last resort: any executable cedar binary
        if os.access(f, os.X_OK):
            return f
    raise SystemExit(f"No cedar-detect-server binary found in {repo / 'bin'}")


# ─────────────────────────── http ───────────────────────────


def base_url(args):
    """Resolve the API base URL from args, then the launch state file, else default."""
    if getattr(args, "base_url", None):
        return args.base_url.rstrip("/")
    state = load_state()
    if state and state.get("base_url"):
        return state["base_url"].rstrip("/")
    return f"http://127.0.0.1:{getattr(args, 'port', DEFAULT_PORT)}"


def http_get(url, timeout=15):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_post(url, payload, timeout=15):
    data = json.dumps(payload if payload is not None else {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_ready(base, timeout=60.0, interval=1.0):
    """Poll /api/status until any HTTP response comes back (server is up)."""
    ok, _, info = wait_ready_any([base], timeout=timeout, interval=interval)
    return ok, info


def wait_ready_any(bases, timeout=60.0, interval=1.0):
    """Poll several candidate base URLs; return (ok, winning_base, info).

    PiFinder binds port 80 when it can and otherwise falls back to 8080, so the
    actual URL is not known until it is listening. We try each candidate every
    round until one answers.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        for base in bases:
            try:
                status, _ = http_get(base + "/api/status", timeout=5)
                return True, base, status
            except Exception as e:  # connection refused while still starting
                last = e
        time.sleep(interval)
    return False, None, last


# ─────────────────────────── state file ───────────────────────────


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return None


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


# ─────────────────────────── process control ───────────────────────────


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def pgid_alive(pgid):
    if not pgid:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_group(pgid, label, grace=4.0):
    """Escalate SIGTERM then SIGKILL on a process group; report what happened."""
    if not pgid or not pgid_alive(pgid):
        return f"{label}: already gone"
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return f"{label}: gone"
    deadline = time.time() + grace
    while time.time() < deadline and pgid_alive(pgid):
        time.sleep(0.2)
    if pgid_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return f"{label}: SIGKILL"
    return f"{label}: SIGTERM"


# ─────────────────────────── commands ───────────────────────────


def cmd_launch(args):
    repo = find_repo(args.repo)
    py = find_python(repo)
    cedar = find_cedar(repo)
    # PiFinder binds port 80 if it can, else 8080. Unless the caller pinned a
    # URL, probe both (the explicit --port first) and record whichever answers.
    if args.base_url:
        candidates = [args.base_url.rstrip("/")]
    else:
        ports = [args.port] + [p for p in (80, 8080) if p != args.port]
        candidates = [f"http://127.0.0.1:{p}" for p in ports]

    existing = load_state()
    if existing and pid_alive(existing.get("main_pid")):
        print(
            f"PiFinder already running (pid {existing['main_pid']}, {existing['base_url']}). "
            "Run `stop` first to relaunch.",
            file=sys.stderr,
        )
        return 1

    cedar_log = open(CEDAR_LOG, "wb")
    pf_log = open(PIFINDER_LOG, "wb")

    cedar_proc = subprocess.Popen(
        [str(cedar), "-p", str(CEDAR_PORT)],
        cwd=str(repo / "bin"),
        stdout=cedar_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pf_cmd = [
        py, "-m", "PiFinder.main",
        "-fh", "--camera", "debug", "--keyboard", "none", "--display", "headless", "-x",
    ]
    pf_proc = subprocess.Popen(
        pf_cmd,
        cwd=str(repo / "python"),
        stdout=pf_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    state = {
        "base_url": candidates[0],  # provisional; updated once we know the real port
        "repo": str(repo),
        "main_pid": pf_proc.pid,
        "main_pgid": os.getpgid(pf_proc.pid),
        "cedar_pid": cedar_proc.pid,
        "cedar_pgid": os.getpgid(cedar_proc.pid),
        "started_at": time.time(),
    }
    save_state(state)
    print(f"cedar-detect-server pid {cedar_proc.pid} (port {CEDAR_PORT})")
    print(f"PiFinder pid {pf_proc.pid}, group {state['main_pgid']}")
    print(
        f"Waiting up to {args.timeout}s for the API "
        f"({', '.join(candidates)}) ...\n"
        "First launch in a fresh checkout rebuilds the catalog cache (~90s)."
    )

    ok, base, info = wait_ready_any(candidates, timeout=args.timeout)
    if not ok:
        print(
            f"API did not come up within {args.timeout}s. "
            f"Check logs: {PIFINDER_LOG}\nLast error: {info}",
            file=sys.stderr,
        )
        if not pid_alive(pf_proc.pid):
            print("PiFinder process exited during startup — see the log above.", file=sys.stderr)
        return 1
    state["base_url"] = base
    save_state(state)
    print(f"PiFinder API is up at {base} (HTTP {info}).")
    return 0


def cmd_ready(args):
    base = base_url(args)
    ok, info = wait_ready(base, timeout=args.timeout)
    if ok:
        print(f"ready ({base}, HTTP {info})")
        return 0
    print(f"not ready after {args.timeout}s: {info}", file=sys.stderr)
    return 1


def cmd_screen(args):
    base = base_url(args)
    status, body = http_get(base + "/api/screen", timeout=15)
    if status != 200:
        print(f"/api/screen returned HTTP {status}", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else LOG_DIR / f"pf_screen_{int(time.time())}.png"
    out.write_bytes(body)
    print(str(out))
    return 0


def cmd_key(args):
    base = base_url(args)
    rc = 0
    for button in args.buttons:
        # Accept a numeric keycode or a named button (UP/DOWN/SQUARE/ALT_*/LNG_* ...)
        payload = {"button": int(button) if button.lstrip("-").isdigit() else button}
        status, body = http_post(base + "/api/key", payload, timeout=10)
        ok = status == 200
        print(f"{button}: HTTP {status}{'' if ok else ' ' + body.decode('utf-8', 'replace')}")
        if not ok:
            rc = 1
        time.sleep(args.delay)
    return rc


def _print_json(status, body):
    try:
        print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))
    except Exception:
        print(body.decode("utf-8", "replace"))
    return 0 if status == 200 else 1


def cmd_status(args):
    base = base_url(args)
    return _print_json(*http_get(base + "/api/status"))


def cmd_solution(args):
    base = base_url(args)
    return _print_json(*http_get(base + "/api/solution"))


def cmd_location(args):
    base = base_url(args)
    return _print_json(*http_get(base + "/api/location"))


def cmd_get(args):
    base = base_url(args)
    path = args.path if args.path.startswith("/") else "/" + args.path
    return _print_json(*http_get(base + path))


def cmd_stop(args):
    state = load_state()
    base = state["base_url"] if state else base_url(args)
    results = []

    # 1) Graceful: ask PiFinder to SIGINT its own group from the inside.
    try:
        status, _ = http_post(base + "/api/stop", {"delay": 0.3}, timeout=5)
        results.append(f"/api/stop: HTTP {status}")
    except Exception as e:
        results.append(f"/api/stop: unreachable ({e})")

    main_pid = state.get("main_pid") if state else None
    main_pgid = state.get("main_pgid") if state else None
    cedar_pgid = state.get("cedar_pgid") if state else None

    # 2) Give the clean shutdown a bounded window to finish on its own.
    deadline = time.time() + args.grace
    while time.time() < deadline and pid_alive(main_pid):
        time.sleep(0.2)

    # 3) Escalate on the group if anything is still alive.
    if main_pgid:
        results.append(kill_group(main_pgid, "pifinder group"))
    elif main_pid and pid_alive(main_pid):
        try:
            os.kill(main_pid, signal.SIGKILL)
            results.append("pifinder pid: SIGKILL")
        except ProcessLookupError:
            pass

    # 4) cedar-detect-server lives in its own group; stop it too.
    if cedar_pgid:
        results.append(kill_group(cedar_pgid, "cedar group"))

    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass

    print("\n".join(results) if results else "nothing to stop")
    return 0


def cmd_kill(args):
    state = load_state()
    if not state:
        print("no launch state file; nothing to kill", file=sys.stderr)
        return 1
    out = []
    if state.get("main_pgid"):
        out.append(kill_group(state["main_pgid"], "pifinder group"))
    if state.get("cedar_pgid"):
        out.append(kill_group(state["cedar_pgid"], "cedar group"))
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    print("\n".join(out))
    return 0


def cmd_logs(args):
    for path in (PIFINDER_LOG, CEDAR_LOG):
        print(f"===== {path} =====")
        try:
            lines = path.read_text(errors="replace").splitlines()
            print("\n".join(lines[-args.lines:]))
        except FileNotFoundError:
            print("(no log yet)")
        print()
    return 0


# ─────────────────────────── argparse ───────────────────────────


def build_parser():
    p = argparse.ArgumentParser(description="Drive a headless PiFinder over its HTTP API.")
    p.add_argument("--base-url", help="API base URL (default from launch state, else http://127.0.0.1:8080)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="API port if no base URL (default 8080)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("launch", help="start cedar + headless PiFinder and wait for the API")
    sp.add_argument("--repo", help="PiFinder repo root (auto-detected by default)")
    sp.add_argument("--timeout", type=float, default=90.0, help="seconds to wait for the API")
    sp.set_defaults(func=cmd_launch)

    sp = sub.add_parser("ready", help="poll until the API answers")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.set_defaults(func=cmd_ready)

    sp = sub.add_parser("screen", help="save GET /api/screen as a PNG")
    sp.add_argument("-o", "--output", help="output PNG path (default: temp dir)")
    sp.set_defaults(func=cmd_screen)

    sp = sub.add_parser("key", help="POST one or more buttons to /api/key, in order")
    sp.add_argument("buttons", nargs="+", help="e.g. UP DOWN SQUARE RIGHT  (or numeric keycodes)")
    sp.add_argument("--delay", type=float, default=0.4, help="seconds between presses (default 0.4)")
    sp.set_defaults(func=cmd_key)

    sp = sub.add_parser("status", help="GET /api/status")
    sp.set_defaults(func=cmd_status)
    sp = sub.add_parser("solution", help="GET /api/solution")
    sp.set_defaults(func=cmd_solution)
    sp = sub.add_parser("location", help="GET /api/location")
    sp.set_defaults(func=cmd_location)

    sp = sub.add_parser("get", help="GET an arbitrary /api/* path")
    sp.add_argument("path", help="e.g. /api/imu")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("stop", help="graceful /api/stop, then escalate if needed")
    sp.add_argument(
        "--grace",
        type=float,
        default=5.0,
        help="seconds to wait for a clean exit before escalating to SIGTERM "
        "(stop returns early as soon as the main process is gone)",
    )
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("kill", help="force-kill the recorded process groups (no graceful step)")
    sp.set_defaults(func=cmd_kill)

    sp = sub.add_parser("logs", help="tail the PiFinder and cedar logs")
    sp.add_argument("-n", "--lines", type=int, default=40)
    sp.set_defaults(func=cmd_logs)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
