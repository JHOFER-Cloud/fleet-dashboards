#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream thanos-io/thanos.
- Clones the upstream repo at the tag pinned in thanos.version
- Copies dashboard JSON files from examples/dashboards/
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..")))
from lib.v1beta1_schema import fix as fix_v1beta1_schema  # noqa: E402  # pyright: ignore[reportMissingImports]
VERSION_FILE = os.path.join(SCRIPT_DIR, "thanos.version")
UPSTREAM_URL = "https://github.com/thanos-io/thanos"
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "Thanos")


def clone_at_tag(tag):
    tmpdir = tempfile.mkdtemp(prefix="thanos-")
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", tag, UPSTREAM_URL, tmpdir],
        check=True,
    )
    return tmpdir


def migrate_rows_to_panels(data):
    """Convert old Grafana rows format (schemaVersion<=16) to modern panels format."""
    if "rows" not in data:
        return data

    panels = []
    y = 0

    for row in data["rows"]:
        is_collapsed = row.get("collapse", False)
        row_y = y

        # Layout panels within the row using span→width conversion (12-col → 24-col)
        px, py, row_h = 0, row_y + 1, 0
        laid_out = []
        for panel in row.get("panels", []):
            w = min(panel.get("span", 12) * 2, 24)
            h = panel.get("height", 7)
            if not isinstance(h, int) or h <= 0:
                h = 7
            if px + w > 24:
                py += row_h
                row_h = 0
                px = 0
            p = dict(panel)
            p["gridPos"] = {"h": h, "w": w, "x": px, "y": py}
            px += w
            row_h = max(row_h, h)
            laid_out.append(p)

        row_panel = {
            "type": "row",
            "title": row.get("title", ""),
            "collapsed": is_collapsed,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": row_y},
            "id": row.get("id", 1000 + row_y),
            "panels": laid_out if is_collapsed else [],
        }

        if is_collapsed:
            panels.append(row_panel)
            y = row_y + 1
        else:
            panels.append(row_panel)
            panels.extend(laid_out)
            y = py + row_h

    data = {k: v for k, v in data.items() if k != "rows"}
    data["panels"] = panels
    data["schemaVersion"] = 36
    return data


def fix_job_selectors(data):
    """Broaden job variable regex to match release-prefixed names.

    Upstream patterns like .*thanos-store.* don't match our job labels
    (e.g. thanos-infra-storegateway) because the release suffix sits between
    'thanos' and the component name.  Replace with .*thanos.*store.* etc.
    """
    import re
    for t in data.get("templating", {}).get("list", []):
        if t.get("name") != "job":
            continue
        q = t.get("query", "")
        if isinstance(q, dict):
            q["query"] = re.sub(r"\.\*thanos-([a-z-]+)\.\*", r".*thanos.*\1.*", q.get("query", ""))
        elif isinstance(q, str):
            t["query"] = re.sub(r"\.\*thanos-([a-z-]+)\.\*", r".*thanos.*\1.*", q)
    return data


def strip_dashboard_links(panels):
    """Remove old-style panel links with type=dashboard — they reference dashboards
    by title which modern Grafana can't resolve, and crash when rendered from
    collapsed rows."""
    result = []
    for p in panels:
        if p.get("links"):
            p = {**p, "links": [l for l in p["links"] if l.get("type") != "dashboard"]}
        if p.get("panels"):
            p = {**p, "panels": strip_dashboard_links(p["panels"])}
        result.append(p)
    return result


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    print(f"Cloning {UPSTREAM_URL} at {tag}...")
    tmpdir = clone_at_tag(tag)

    try:
        upstream = os.path.join(tmpdir, "examples", "dashboards")
        os.makedirs(OUTPUT, exist_ok=True)

        dashboard_files = sorted(f for f in os.listdir(upstream) if f.endswith(".json"))
        if not dashboard_files:
            print("ERROR: No dashboard JSON files found", file=sys.stderr)
            sys.exit(1)

        for name in dashboard_files:
            with open(os.path.join(upstream, name)) as fh:
                data = json.load(fh)
            data = migrate_rows_to_panels(data)
            data = fix_job_selectors(data)
            if "panels" in data:
                data["panels"] = strip_dashboard_links(data["panels"])
            data = fix_v1beta1_schema(data)

            dst = os.path.join(OUTPUT, name)
            with open(dst, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")

            print(f"Generated: sync/K8s/Thanos/{name}")
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
