"""End-to-end delta upgrade test. run.sh starts it in bwrap, test store at /nix.

Same steps as nixos_upgrade.run_upgrade up to the build: dry-run estimate,
delta prefetch against the live differ, nix build with the staged cache. No
activation, no reboot.

With a closure file (from an earlier run, see run.sh), the build uses the
local check of that closure, as with a differ that lists the closure, and
the result must equal the dry run.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3] / "python"
sys.path.insert(0, str(REPO))

from PiFinder import delta_updates, nixos_upgrade  # noqa: E402

target = sys.argv[1]
work = Path(sys.argv[2])
work.mkdir(parents=True, exist_ok=True)
delta_updates.WORK_ROOT = work / "delta-work"
os.environ.setdefault("PIFINDER_DELTA_URL", "https://deltas.pifinder.eu")

statuses = []


def status(s):
    statuses.append((round(time.monotonic() - t0, 1), s))
    print(f"[{statuses[-1][0]:6.1f}s] status: {s}", flush=True)


def load_closure(path):
    """`nix path-info -r --json` output as ((store path, NAR size), ...)."""
    if not path.exists():
        return ()
    info = json.loads(path.read_text())
    if isinstance(info, dict):
        items = [(p, i["narSize"]) for p, i in info.items()]
    else:
        items = [(i["path"], i["narSize"]) for i in info]
    # The differ lists the toplevel first.
    return tuple(sorted(items, key=lambda item: item[0] != target))


closure = load_closure(Path(sys.argv[3])) if len(sys.argv) > 3 else ()
t0 = time.monotonic()
status("checking")
estimate = nixos_upgrade.estimate_download(target)
dry_run_s = time.monotonic() - t0
print(f"missing paths: {len(estimate.paths)}, total bytes: {estimate.total_bytes}")
closure_ok = True
if closure:
    t1 = time.monotonic()
    checked = nixos_upgrade.estimate_from_closure(
        target, closure, progress=lambda d, t: status(f"checking {d}/{t}")
    )
    check_s = time.monotonic() - t1
    print(f"dry run {dry_run_s:.1f} s, local check of {len(closure)} paths {check_s:.1f} s")
    # The dry run prints the total with one decimal ("12.5 MiB").
    closure_ok = (
        checked is not None
        and set(checked.paths) == set(estimate.paths)
        and abs(checked.total_bytes - estimate.total_bytes)
        <= max(0.01 * estimate.total_bytes, 64 * 1024)
    )
    print(
        "closure check equals the dry run:",
        closure_ok,
        None if checked is None else (len(checked.paths), checked.total_bytes),
    )
    if checked is not None:
        estimate = checked
else:
    print("no closure file: the local check is not compared (first run)")
for p in estimate.paths:
    print("   ", p)

staged = delta_updates.prefetch_deltas(
    target,
    estimate.paths,
    nixos_upgrade.CACHES,
    progress=lambda step, d, t: status(f"patching {step} {d}/{t}"),
)
print(f"staged: {staged.count}, failed: {staged.failed}, url: {staged.url}")
staged_paths = []
if staged.root:
    for ni in sorted((staged.root / "cache").glob("*.narinfo")):
        m = re.search(r"^StorePath: (.*)$", ni.read_text(), re.M)
        staged_paths.append(m.group(1))
for p in staged_paths:
    print("   staged:", p)

log = work / "build.log"
full_log = work / "build-full.log"
_popen = nixos_upgrade.subprocess.Popen


class _Tee:
    def __init__(self, stream, path):
        self.stream, self.out = stream, open(path, "w")

    def __iter__(self):
        for line in self.stream:
            self.out.write(line)
            yield line
        self.out.close()


def _popen_tee(args, **kw):
    proc = _popen(args, **kw)
    proc.stdout = _Tee(proc.stdout, full_log)
    return proc


nixos_upgrade.subprocess.Popen = _popen_tee
try:
    rc = nixos_upgrade.run_build(
        target,
        estimate,
        status_file=work / "status",
        log_file=log,
        substituter=staged.url,
    )
finally:
    staged.cleanup()
status(f"build rc={rc}")

from_file = set()
for line in full_log.read_text().splitlines():
    if line.startswith("@nix "):
        try:
            msg = json.loads(line[5:])
        except ValueError:
            continue
        text = msg.get("text", "") + " " + " ".join(map(str, msg.get("fields", [])))
        if "file://" in text:
            for p in re.findall(r"/nix/store/[a-z0-9]{32}-[^ '\"]+", text):
                from_file.add(p)
print(
    f"paths substituted from the staged cache: {len(from_file & set(staged_paths))}"
    f" of {len(staged_paths)} staged"
)
print("target present:", Path(target).exists())
print(
    "RESULT:",
    "PASS"
    if rc == 0
    and closure_ok
    and Path(target).exists()
    and staged.count > 0
    and from_file >= set(staged_paths)
    else "FAIL",
)
