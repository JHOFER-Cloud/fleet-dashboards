#!/usr/bin/env python3
"""
Generate the Comet dashboard from upstream g0ldyy/comet.
- Reads the tag from comet.version
- Downloads deployment/monitoring/grafana/dashboards/comet-overview.json
- Writes sync/K8s/Deploy/Jelly-Stack/comet.json

Upstream targets its compose stack: a fixed datasource uid and job="comet".
Here the datasource picks the cluster and the PodMonitor names the job
jelly-stack/comet.
"""

import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..")))
from lib.v1beta1_schema import fix as fix_v1beta1_schema  # noqa: E402  # pyright: ignore[reportMissingImports]

VERSION_FILE = os.path.join(SCRIPT_DIR, "comet.version")
RAW_URL = "https://raw.githubusercontent.com/g0ldyy/comet/{tag}/deployment/monitoring/grafana/dashboards/comet-overview.json"
OUTPUT = os.path.join(
    SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "Deploy", "Jelly-Stack", "comet.json"
)

UID = "jelly_comet"
TITLE = "Comet"
UPSTREAM_DS_UID = "comet-prometheus"
DS_REF = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}
PROMETHEUS_DS = {"text": "k8_live_hla1", "value": "eef9f89usay9sb"}
JOB_SELECTOR = 'job="comet"'
OUR_JOB_SELECTOR = 'job="jelly-stack/comet"'

DS_VARIABLE = {
    "current": dict(PROMETHEUS_DS),
    "hide": 0,
    "includeAll": False,
    "name": "DS_PROMETHEUS",
    "options": [],
    "query": "prometheus",
    "refresh": 1,
    "type": "datasource",
    "label": "Datasource",
}


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "fleet-dashboards-generate.py"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GET {url} returned {resp.status}")
        return resp.read().decode("utf-8")


def fix_datasources(node):
    """Point every reference to upstream's fixed datasource at the variable."""
    replaced = 0
    if isinstance(node, dict):
        ds = node.get("datasource")
        if isinstance(ds, dict) and ds.get("uid") == UPSTREAM_DS_UID:
            node["datasource"] = dict(DS_REF)
            replaced += 1
        for value in node.values():
            replaced += fix_datasources(value)
    elif isinstance(node, list):
        for item in node:
            replaced += fix_datasources(item)
    return replaced


def fix_job_selector(data):
    replaced = 0

    def walk(panels):
        nonlocal replaced
        for panel in panels:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                if JOB_SELECTOR in expr:
                    target["expr"] = expr.replace(JOB_SELECTOR, OUR_JOB_SELECTOR)
                    replaced += 1
            walk(panel.get("panels", []))

    walk(data["panels"])
    if not replaced:
        raise SystemExit(f"ERROR: no {JOB_SELECTOR} selector found upstream")
    return data


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    data = json.loads(fetch(RAW_URL.format(tag=tag)))
    if "panels" not in data:
        raise SystemExit("ERROR: upstream dashboard has no 'panels'")

    if not fix_datasources(data):
        raise SystemExit(f"ERROR: no {UPSTREAM_DS_UID} datasource found upstream")
    data = fix_job_selector(data)
    data["templating"]["list"].insert(0, dict(DS_VARIABLE))
    data["uid"] = UID
    data["title"] = TITLE
    data.pop("id", None)
    data.pop("version", None)
    data = fix_v1beta1_schema(data)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

    print(
        f"Generated: sync/K8s/Deploy/Jelly-Stack/{os.path.basename(OUTPUT)} from {tag}"
    )


if __name__ == "__main__":
    main()
