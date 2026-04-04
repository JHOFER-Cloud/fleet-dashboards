#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream featheredtoast/satisfactory-monitoring.
- Clones the upstream repo at the commit pinned in satisfactory-monitoring.version
- Replaces datasource UIDs to match local configuration
- Adds satisfactory_frm_ prefix to all Prometheus metric names in PromQL expressions
  (relies on the fact that in PromQL, only metric names appear immediately before '{')
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(SCRIPT_DIR, "satisfactory-monitoring.version")
UPSTREAM_URL = "https://github.com/featheredtoast/satisfactory-monitoring"
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "AMP", "Satisfactory")

# Datasource UID replacements: upstream UID -> local UID
DATASOURCE_UIDS = {
    "PBFA97CFB590B2093": "eef9f89usay9sb",  # Prometheus (live)
    "GhzMNppVk": "satisfactory-cache",  # PostgreSQL (frmcache)
}

# In PromQL, only metric names appear immediately before '{'.
# Match any such name not already prefixed.
METRIC_RE = re.compile(
    r"(?<![a-zA-Z0-9_])(?!satisfactory_frm_)([a-z][a-z0-9_:]+)(?=\{)"
)


def clone_at_commit(commit_sha):
    tmpdir = tempfile.mkdtemp(prefix="satisfactory-monitoring-")
    subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", tmpdir, "remote", "add", "origin", UPSTREAM_URL],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", tmpdir, "fetch", "--depth=1", "origin", commit_sha],
        check=True,
    )
    subprocess.run(
        ["git", "-C", tmpdir, "checkout", "FETCH_HEAD"],
        check=True, capture_output=True,
    )
    return tmpdir


def walk(obj):
    if isinstance(obj, dict):
        if obj.get("uid") in DATASOURCE_UIDS:
            obj["uid"] = DATASOURCE_UIDS[obj["uid"]]
        return {
            k: (
                METRIC_RE.sub(r"satisfactory_frm_\1", v)
                if k == "expr" and isinstance(v, str)
                else walk(v)
            )
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [walk(v) for v in obj]
    return obj


def main():
    with open(VERSION_FILE) as fh:
        commit_sha = fh.read().strip()

    print(f"Cloning {UPSTREAM_URL} at {commit_sha[:12]}...")
    tmpdir = clone_at_commit(commit_sha)

    try:
        upstream = os.path.join(tmpdir, "grafana", "dashboards")
        os.makedirs(OUTPUT, exist_ok=True)

        dashboard_files = sorted(f for f in os.listdir(upstream) if f.endswith(".json"))
        if not dashboard_files:
            print(f"ERROR: No dashboard JSON files found in {upstream}", file=sys.stderr)
            sys.exit(1)

        for name in dashboard_files:
            with open(os.path.join(upstream, name)) as fh:
                data = json.load(fh)

            data = walk(data)

            dst = os.path.join(OUTPUT, name)
            with open(dst, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")

            print(f"Generated: sync/AMP/Satisfactory/{name}")
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
