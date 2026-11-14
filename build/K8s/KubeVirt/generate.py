#!/usr/bin/env python3
"""
Generate the KubeVirt Top Consumers dashboard from upstream kubevirt/monitoring.

- Reads the commit pinned in kubevirt-monitoring.version
- Downloads dashboards/openshift/kubevirt-top-consumers.json (the only maintained
  Grafana dashboard upstream; the Grafana control-plane one dates from 2022)
- Upstream panels reference $datasource without defining it (the OpenShift console
  injects it), so a datasource variable pinned to the live cluster is added
- Writes sync/K8s/KubeVirt/top_consumers.json
"""
import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..")))
from lib.v1beta1_schema import fix as fix_v1beta1_schema  # noqa: E402  # pyright: ignore[reportMissingImports]

VERSION_FILE = os.path.join(SCRIPT_DIR, "kubevirt-monitoring.version")
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "KubeVirt", "top_consumers.json")
RAW_BASE = "https://raw.githubusercontent.com/kubevirt/monitoring"
UPSTREAM_PATH = "dashboards/openshift/kubevirt-top-consumers.json"

PROMETHEUS_DS = {"text": "k8_live_hla1", "value": "eef9f89usay9sb"}

DATASOURCE_VAR = {
    "name": "datasource",
    "label": "Datasource",
    "type": "datasource",
    "query": "prometheus",
    "current": dict(PROMETHEUS_DS),
    "hide": 0,
    "refresh": 1,
    "regex": "",
    "options": [],
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-dashboards-generate.py"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GET {url} returned {resp.status}")
        return resp.read().decode("utf-8")


def main():
    with open(VERSION_FILE) as fh:
        commit = fh.read().strip()

    print(f"kubevirt/monitoring commit: {commit}")
    data = json.loads(fetch(f"{RAW_BASE}/{commit}/{UPSTREAM_PATH}"))
    if "panels" not in data:
        sys.exit(f"{UPSTREAM_PATH} has no panels, upstream format changed")

    data = fix_v1beta1_schema(data)
    templating = data.setdefault("templating", {}).setdefault("list", [])
    templating[:] = [v for v in templating if v.get("name") != "datasource"]
    templating.insert(0, dict(DATASOURCE_VAR))
    data.pop("id", None)
    data["uid"] = "kubevirt-top-consumers"
    data["title"] = "KubeVirt / Top Consumers"
    data["tags"] = ["kubevirt"]
    data["time"] = {"from": "now-2d", "to": "now"}

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print("Wrote sync/K8s/KubeVirt/top_consumers.json")


if __name__ == "__main__":
    main()
