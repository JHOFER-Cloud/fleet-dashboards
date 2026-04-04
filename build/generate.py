#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream featheredtoast/satisfactory-monitoring.
- Replaces datasource UIDs to match local configuration
- Adds satisfactory_frm_ prefix to all Prometheus metric names in PromQL expressions
  (relies on the fact that in PromQL, only metric names appear immediately before '{')
"""
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPSTREAM = os.path.join(SCRIPT_DIR, "satisfactory-monitoring", "grafana", "dashboards")
OUTPUT = os.path.join(SCRIPT_DIR, "..", "sync", "AMP", "Satisfactory")

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
    os.makedirs(OUTPUT, exist_ok=True)

    dashboard_files = sorted(f for f in os.listdir(UPSTREAM) if f.endswith(".json"))
    if not dashboard_files:
        print(f"ERROR: No dashboard JSON files found in {UPSTREAM}", file=sys.stderr)
        sys.exit(1)

    for name in dashboard_files:
        with open(os.path.join(UPSTREAM, name)) as fh:
            data = json.load(fh)

        data = walk(data)

        dst = os.path.join(OUTPUT, name)
        with open(dst, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

        print(f"Generated: sync/AMP/Satisfactory/{name}")


if __name__ == "__main__":
    main()
