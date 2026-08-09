#!/usr/bin/env python3
"""
Generate the Renovate Operator dashboard from upstream mogenius/renovate-operator.
- Clones the upstream repo at the tag pinned in renovate-operator.version
- Extracts the dashboard JSON embedded in the chart's ConfigMap template

Unlike the other generators the dashboard is not a standalone file upstream; it
is inlined in charts/renovate-operator/templates/dashboard.yaml under the
`renovate-operator.json: |` key, wrapped in Helm conditionals.
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

VERSION_FILE = os.path.join(SCRIPT_DIR, "renovate-operator.version")
UPSTREAM_URL = "https://github.com/mogenius/renovate-operator"
TEMPLATE = os.path.join("charts", "renovate-operator", "templates", "dashboard.yaml")
DASHBOARD_KEY = "renovate-operator.json"
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "Misc", "renovate.json")


def clone_at_tag(tag):
    tmpdir = tempfile.mkdtemp(prefix="renovate-operator-")
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", tag, UPSTREAM_URL, tmpdir],
        check=True,
    )
    return tmpdir


def extract_dashboard(path):
    """Pull the JSON out of the `<key>: |` literal block in a Helm template.

    The file is not parseable as YAML because of the surrounding Go template
    directives, so the block is located and dedented by hand.
    """
    with open(path) as fh:
        lines = fh.read().splitlines()

    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{DASHBOARD_KEY}:"):
            start = i + 1
            break
    if start is None:
        raise SystemExit(f"ERROR: {DASHBOARD_KEY} not found in {path}")

    block = []
    indent = None
    for line in lines[start:]:
        if not line.strip():
            block.append("")
            continue
        stripped = len(line) - len(line.lstrip())
        if indent is None:
            indent = stripped
        elif stripped < indent:
            break
        block.append(line[indent:])

    return json.loads("\n".join(block))


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    print(f"Cloning {UPSTREAM_URL} at {tag}...")
    tmpdir = clone_at_tag(tag)

    try:
        data = extract_dashboard(os.path.join(tmpdir, TEMPLATE))
        data = fix_v1beta1_schema(data)

        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

        print(f"Generated: sync/K8s/Misc/{os.path.basename(OUTPUT)}")
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
