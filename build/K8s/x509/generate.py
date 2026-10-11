#!/usr/bin/env python3
"""
Generate the x509-certificate-exporter dashboard from upstream enix/x509-certificate-exporter.

- Reads the tag from x509-certificate-exporter.version
- Downloads chart/grafana-dashboards/x509-certificate-exporter.json
- Writes raw Grafana JSON to sync/K8s/Misc/x509-certificate-exporter.json

The Host Files / Host Paths panels stay empty: only the Secrets exporter is
deployed, not the hostPathsExporter DaemonSet.
"""
import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..")))
from lib.v1beta1_schema import fix as fix_v1beta1_schema  # noqa: E402  # pyright: ignore[reportMissingImports]

VERSION_FILE = os.path.join(SCRIPT_DIR, "x509-certificate-exporter.version")
RAW_BASE = "https://raw.githubusercontent.com/enix/x509-certificate-exporter"
UPSTREAM_PATH = "chart/grafana-dashboards/x509-certificate-exporter.json"
OUTPUT = os.path.join(
    SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "Misc", "x509-certificate-exporter.json"
)

PROMETHEUS_DS = {"text": "k8_live_hla1", "value": "eef9f89usay9sb"}

# Match the HelmRelease's warningDaysLeft/criticalDaysLeft in fleet, so the
# dashboard's bands line up with what actually alerts.
THRESHOLDS = {"warning_threshold": "7", "critical_threshold": "3"}


def pin_prometheus_datasource(data):
    for var in data.get("templating", {}).get("list", []):
        if var.get("type") == "datasource" and var.get("query") == "prometheus":
            var["current"] = dict(PROMETHEUS_DS)
    return data


def pin_thresholds(data):
    for var in data.get("templating", {}).get("list", []):
        value = THRESHOLDS.get(var.get("name"))
        if value and var.get("type") == "custom":
            var["current"] = {"text": value, "value": value}
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

    url = f"{RAW_BASE}/{tag}/{UPSTREAM_PATH}"
    print(f"x509-certificate-exporter tag: {tag}")
    print(f"  <- {UPSTREAM_PATH}")

    data = json.loads(fetch(url))
    if "panels" not in data:
        raise SystemExit("ERROR: upstream dashboard has no 'panels'")

    data = fix_v1beta1_schema(data)
    data = pin_prometheus_datasource(data)
    data = pin_thresholds(data)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

    print("Generated: sync/K8s/Misc/x509-certificate-exporter.json")


if __name__ == "__main__":
    main()
