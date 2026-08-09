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
import re
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


def unescape_helm(text):
    """Undo Helm's escaping of Grafana's own interpolations.

    Grafana legend fields use {{label}}, which the chart has to escape so Helm
    does not evaluate it. Helm resolves that at render time; this generator reads
    the raw template, so it has to do the same.
    """
    return re.sub(r"\{\{`(.*?)`\}\}", r"\1", text)


# Grafana displays reducers under these names, which is what sortBy matches on.
CALC_DISPLAY_NAMES = {
    "lastNotNull": "Last *",
    "last": "Last",
    "max": "Max",
    "mean": "Mean",
    "min": "Min",
    "sum": "Total",
    "count": "Count",
}

# When a legend carries several calcs, sort by the first of these present.
CALC_PRIORITY = ["lastNotNull", "last", "max", "sum", "mean", "count", "min"]


def walk_panels(panels):
    for panel in panels:
        yield panel
        yield from walk_panels(panel.get("panels", []))


def value_column(panel):
    """Name the numeric column of a table panel carries after its organize
    transformation, or None when the value is dropped."""
    for transform in panel.get("transformations", []):
        if transform.get("id") != "organize":
            continue
        options = transform.get("options", {})
        if options.get("excludeByName", {}).get("Value"):
            return None
        return options.get("renameByName", {}).get("Value") or "Value"
    return None


def is_timestamp_column(panel, column):
    """True when the column renders as a date, in which case soonest is the
    useful top row rather than largest."""
    for override in panel.get("fieldConfig", {}).get("overrides", []):
        if override.get("matcher", {}).get("options") != column:
            continue
        for prop in override.get("properties", []):
            if prop.get("id") == "unit" and str(prop.get("value", "")).startswith(
                "dateTime"
            ):
                return True
    return False


def sort_panels(data):
    """Sort legend tables and table panels by value, highest first."""
    for panel in walk_panels(data.get("panels", [])):
        legend = panel.get("options", {}).get("legend", {})
        if legend.get("displayMode") == "table":
            for calc in CALC_PRIORITY:
                if calc in (legend.get("calcs") or []):
                    legend["sortBy"] = CALC_DISPLAY_NAMES[calc]
                    legend["sortDesc"] = True
                    break

        if panel.get("type") == "table":
            column = value_column(panel)
            if column:
                panel.setdefault("options", {})["sortBy"] = [
                    {
                        "displayName": column,
                        "desc": not is_timestamp_column(panel, column),
                    }
                ]
    return data


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

    return json.loads(unescape_helm("\n".join(block)))


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    print(f"Cloning {UPSTREAM_URL} at {tag}...")
    tmpdir = clone_at_tag(tag)

    try:
        data = extract_dashboard(os.path.join(tmpdir, TEMPLATE))
        data = sort_panels(data)
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
