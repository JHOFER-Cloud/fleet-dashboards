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

# Pin Grafana datasource template variables to the live cluster's Prometheus.
# Matches the convention used by sync/K8s/Network/traefik.json so dashboards
# load with a usable datasource by default instead of an empty selector.
PROMETHEUS_DS = {"text": "k8_live_hla1", "value": "eef9f89usay9sb"}

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


def pin_prometheus_datasource(data):
    """Set the default value of any datasource template variable querying
    'prometheus' to the live cluster's UID, so dashboards open with a usable
    datasource instead of an empty selector."""
    for var in data.get("templating", {}).get("list", []):
        if var.get("type") == "datasource" and var.get("query") == "prometheus":
            var["current"] = dict(PROMETHEUS_DS)
    return data


def pin_time_range(data):
    """Default time range to the last 2 days. Override Cilium's upstream
    default (typically now-1h) which is too narrow for spotting trends."""
    data["time"] = {"from": "now-2d", "to": "now"}
    return data


def pin_tags(data, out_name):
    """Tag dashboards so Hubble / Network Overview's cross-dashboard dropdowns
    actually find their targets. Upstream only tags some dashboards (and uses a
    stale `kubecon-demo` tag); replace with consistent ones derived from the
    output filename:
      hubble_*  → ['cilium', 'hubble']
      cilium_*  → ['cilium', 'cilium-overview']
    """
    base = out_name[:-5] if out_name.endswith(".json") else out_name
    if base.startswith("hubble"):
        data["tags"] = ["cilium", "hubble"]
    elif base.startswith("cilium"):
        data["tags"] = ["cilium", "cilium-overview"]
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
        data = pin_prometheus_datasource(data)
        data = pin_time_range(data)
        data = pin_tags(data, out_name)

        dst = os.path.join(OUTPUT, out_name)
        with open(dst, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

    print(f"Wrote {len(DASHBOARDS)} dashboards to sync/K8s/Cilium/")


if __name__ == "__main__":
    main()
