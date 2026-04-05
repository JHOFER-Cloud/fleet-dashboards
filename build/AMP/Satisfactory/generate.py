#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream featheredtoast/satisfactory-monitoring.
- Clones the upstream repo at the commit pinned in satisfactory-monitoring.version
- Replaces datasource UIDs to match local configuration
- Adds satisfactory_frm_ prefix to all Prometheus metric names:
  - In PromQL expressions (metric names before '{')
  - In label_values() calls (variable queries/definitions)
  - In byName matcher options (fieldConfig overrides)
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

# String replacements applied to all string values
STRING_REPLACEMENTS = {
    "http://fakeserver:8080": "http://amp-p1.vm-ct.hla1.jhofer.lan:38080",
    "http://frm-server:8080": "http://amp-p1.vm-ct.hla1.jhofer.lan:38080",
    "http://192.168.2.97:8080": "http://amp-p1.vm-ct.hla1.jhofer.lan:38080",
}

# Datasource UID replacements: upstream UID -> local UID
DATASOURCE_UIDS = {
    "PBFA97CFB590B2093": "eef9f89usay9sb",  # Prometheus (live)
    "GhzMNppVk": "satisfactory-cache",  # PostgreSQL (frmcache)
}

# Metric name immediately before '{' in PromQL (expr fields, variable queries)
METRIC_SELECTOR_RE = re.compile(
    r"(?<![a-zA-Z0-9_])(?!satisfactory_frm_)([a-z][a-z0-9_:]+)(?=\{)"
)

# Metric name as first argument to label_values() in two-argument form:
# label_values(metric_name, label) or label_values(metric_name{...}, label)
# Single-argument form label_values(label_name) must NOT be matched.
LABEL_VALUES_RE = re.compile(
    r"(?<=label_values\()(?!satisfactory_frm_)([a-z][a-z0-9_:]+)(?=[,{])"
)


def prefix_metrics(s):
    s = METRIC_SELECTOR_RE.sub(r"satisfactory_frm_\1", s)
    s = LABEL_VALUES_RE.sub(r"satisfactory_frm_\1", s)
    return s


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


def filter_panels(panels):
    return [
        p for p in panels
        if p.get("type") != "alertlist"
        and not (p.get("type") == "row" and p.get("title") == "Alerts")
    ]


def walk(obj):
    if isinstance(obj, dict):
        if obj.get("uid") in DATASOURCE_UIDS:
            obj["uid"] = DATASOURCE_UIDS[obj["uid"]]
        # byName matchers reference the full metric name without '{}'
        if obj.get("id") == "byName" and isinstance(obj.get("options"), str):
            options = obj["options"]
            if not options.startswith("satisfactory_frm_"):
                obj = {**obj, "options": f"satisfactory_frm_{options}"}
        return {
            k: (
                prefix_metrics(v)
                if k in ("expr", "definition") and isinstance(v, str)
                else (
                    prefix_metrics(v)
                    if k == "query" and isinstance(v, str)
                    else walk(v)
                )
            )
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [walk(v) for v in obj]
    elif isinstance(obj, str):
        for old, new in STRING_REPLACEMENTS.items():
            obj = obj.replace(old, new)
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
            if "panels" in data:
                data["panels"] = filter_panels(data["panels"])

            dst = os.path.join(OUTPUT, name)
            with open(dst, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")

            print(f"Generated: sync/AMP/Satisfactory/{name}")
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
