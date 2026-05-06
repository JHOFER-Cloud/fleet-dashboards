#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream cilium/cilium.

- Reads the tag from cilium.version
- Downloads each dashboard JSON from install/kubernetes/cilium/files/.../dashboards/
- Writes raw Grafana JSON to sync/K8s/Cilium/<output>.json

The {{label}} strings inside the JSON look like Helm placeholders but are
Grafana legend formatters (resolved at render time against Prometheus labels);
no templating is required.
"""
import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(SCRIPT_DIR, "cilium.version")
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "Cilium")
RAW_BASE = "https://raw.githubusercontent.com/cilium/cilium"

# (upstream_path, output_filename) — output_filename is what lands in sync/K8s/Cilium/
DASHBOARDS = [
    (
        "install/kubernetes/cilium/files/cilium-agent/dashboards/cilium-dashboard.json",
        "cilium_agent.json",
    ),
    (
        "install/kubernetes/cilium/files/cilium-operator/dashboards/cilium-operator-dashboard.json",
        "cilium_operator.json",
    ),
    (
        "install/kubernetes/cilium/files/hubble/dashboards/hubble-dashboard.json",
        "hubble.json",
    ),
    (
        "install/kubernetes/cilium/files/hubble/dashboards/hubble-dns-namespace.json",
        "hubble_dns.json",
    ),
    (
        "install/kubernetes/cilium/files/hubble/dashboards/hubble-l7-http-metrics-by-workload.json",
        "hubble_l7.json",
    ),
    (
        "install/kubernetes/cilium/files/hubble/dashboards/hubble-network-overview-namespace.json",
        "hubble_network.json",
    ),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-dashboards-generate.py"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GET {url} returned {resp.status}")
        return resp.read().decode("utf-8")


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    print(f"Cilium tag: {tag}")
    os.makedirs(OUTPUT, exist_ok=True)

    for upstream_path, out_name in DASHBOARDS:
        url = f"{RAW_BASE}/{tag}/{upstream_path}"
        print(f"  → {out_name} <- {upstream_path}")
        body = fetch(url)
        # Validate it parses as JSON before writing
        data = json.loads(body)
        if "panels" not in data and "rows" not in data:
            print(f"WARN: {out_name} has neither 'panels' nor 'rows'", file=sys.stderr)

        dst = os.path.join(OUTPUT, out_name)
        with open(dst, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

    print(f"Wrote {len(DASHBOARDS)} dashboards to sync/K8s/Cilium/")


if __name__ == "__main__":
    main()
