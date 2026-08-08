#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream mrlhansen/idrac_exporter.

- Reads the tag from idrac.version
- Downloads each dashboard JSON from grafana/
- Writes raw Grafana JSON to sync/idrac/<output>.json
"""
import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, "..")))
from lib.v1beta1_schema import fix as fix_v1beta1_schema  # noqa: E402  # pyright: ignore[reportMissingImports]
VERSION_FILE = os.path.join(SCRIPT_DIR, "idrac.version")
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "sync", "idrac")
RAW_BASE = "https://raw.githubusercontent.com/mrlhansen/idrac_exporter"

# The exporter only runs in the dev cluster, so pin the datasource there.
PROMETHEUS_DS = {"text": "k8_dev_hla1", "value": "aef9f9k9lvwn4b"}

# (upstream_filename, output_filename)
DASHBOARDS = [
    ("idrac.json", "idrac.json"),
    ("idrac_overview.json", "idrac_overview.json"),
    ("status-alternative.json", "status_alternative.json"),
]


def pin_prometheus_datasource(data):
    for var in data.get("templating", {}).get("list", []):
        if var.get("type") == "datasource" and var.get("query") == "prometheus":
            var["current"] = dict(PROMETHEUS_DS)
    return data


def use_instant_table_queries(data):
    """Make table panels use instant queries.

    idrac.json queries inventory metrics (DIMMs, drives, ports) as range
    queries in table format, so each series contributes one row per sample
    and joinByField multiplies them out — a single DIMM renders as a dozen
    identical rows. status-alternative.json does the same panels correctly
    with instant queries.
    """

    def walk(panels):
        for panel in panels:
            if panel.get("type") == "table":
                for target in panel.get("targets", []):
                    if target.get("format") == "table":
                        target["instant"] = True
                        target["range"] = False
            if panel.get("panels"):
                walk(panel["panels"])

    walk(data.get("panels", []))
    return data


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-dashboards-generate.py"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GET {url} returned {resp.status}")
        return resp.read().decode("utf-8")


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    print(f"idrac_exporter tag: {tag}")
    os.makedirs(OUTPUT, exist_ok=True)

    for upstream_name, out_name in DASHBOARDS:
        url = f"{RAW_BASE}/{tag}/grafana/{upstream_name}"
        print(f"  → {out_name} <- grafana/{upstream_name}")
        data = json.loads(fetch(url))
        if "panels" not in data and "rows" not in data:
            print(f"WARN: {out_name} has neither 'panels' nor 'rows'", file=sys.stderr)
        data = fix_v1beta1_schema(data)
        data = pin_prometheus_datasource(data)
        data = use_instant_table_queries(data)

        dst = os.path.join(OUTPUT, out_name)
        with open(dst, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

    print(f"Wrote {len(DASHBOARDS)} dashboards to sync/idrac/")


if __name__ == "__main__":
    main()
