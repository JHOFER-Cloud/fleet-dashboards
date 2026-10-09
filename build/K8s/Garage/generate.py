#!/usr/bin/env python3
"""
Generate the Garage dashboard from upstream rajsinghtech/garage-operator.
- Reads the tag from garage-operator.version
- Downloads charts/garage-operator/dashboards/garage-prometheus.json
- Writes sync/K8s/Storage/garage.json

Each cluster runs several GarageClusters (one per namespace) and upstream
queries only select job="garage", so a namespace filter is injected.
"""
import json
import os
import re
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..")))
from lib.v1beta1_schema import fix as fix_v1beta1_schema  # noqa: E402  # pyright: ignore[reportMissingImports]
VERSION_FILE = os.path.join(SCRIPT_DIR, "garage-operator.version")
RAW_URL = "https://raw.githubusercontent.com/rajsinghtech/garage-operator/{tag}/charts/garage-operator/dashboards/garage-prometheus.json"
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "K8s", "Storage", "garage.json")

# Keeps the identity of the dashboard this generator replaced.
UID = "s3_garage"
PROMETHEUS_DS = {"text": "k8_live_hla1", "value": "eef9f89usay9sb"}
JOB_SELECTOR = 'job="garage"'
FILTERED_SELECTOR = 'job="garage", namespace=~"$namespace", service=~"$service"'
# Needs the operator's own metrics endpoint, which we don't scrape.
DROP_ROW = "Bucket Quotas"
# Upstream names that Garage v2 doesn't export.
METRIC_RENAMES = {"rpc_netapp_request_counter": "rpc_request_counter"}
# Upstream runs histogram_quantile on the bare histogram name; only _bucket exists.
HISTOGRAM_RE = re.compile(r"\b([a-z0-9_]+_duration)\{")


def label_var(name, label, selector):
    query = f"label_values(api_s3_request_counter{{{selector}}}, {name})"
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
        "definition": query,
        "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
        "refresh": 1,
        "includeAll": True,
        "multi": True,
        "current": {"text": ["All"], "value": ["$__all"]},
        "options": [],
        "hide": 0,
        "regex": "",
        "sort": 1,
    }


# One service per GarageCluster; pod names carry the cluster name, IPs don't.
VARIABLES = [
    label_var("namespace", "Namespace", 'job="garage"'),
    label_var("service", "Service", 'job="garage", namespace=~"$namespace"'),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-dashboards-generate.py"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GET {url} returned {resp.status}")
        return resp.read().decode("utf-8")


def drop_row(data, title):
    """Remove an expanded row and the panels laid out below it, up to the next row."""
    kept, dropping = [], False
    for panel in data["panels"]:
        if panel.get("type") == "row":
            dropping = panel.get("title") == title
        if not dropping:
            kept.append(panel)
    if len(kept) == len(data["panels"]):
        raise SystemExit(f"ERROR: row {title!r} not found upstream")
    data["panels"] = kept
    return data


def fix_exprs(data):
    filtered = 0
    for panel in data["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if JOB_SELECTOR in expr:
                expr = expr.replace(JOB_SELECTOR, FILTERED_SELECTOR)
                filtered += 1
            if "{{instance}}" in target.get("legendFormat", ""):
                target["legendFormat"] = target["legendFormat"].replace("{{instance}}", "{{pod}}")
                # A pod can have several series (e.g. after a restart); show one line each.
                expr = f"max by (pod) ({expr})"
            for old, new in METRIC_RENAMES.items():
                expr = re.sub(rf"\b{old}\b", new, expr)
            if "histogram_quantile" in expr:
                expr = HISTOGRAM_RE.sub(r"\1_bucket{", expr)
            target["expr"] = expr
    if not filtered:
        raise SystemExit(f"ERROR: no {JOB_SELECTOR} selectors found upstream")
    return data


def set_variables(data):
    variables = data["templating"]["list"]
    for var in variables:
        if var.get("type") == "datasource" and var.get("query") == "prometheus":
            var["current"] = dict(PROMETHEUS_DS)
    variables.extend(VARIABLES)
    return data


def main():
    with open(VERSION_FILE) as fh:
        tag = fh.read().strip()

    data = json.loads(fetch(RAW_URL.format(tag=tag)))
    data = drop_row(data, DROP_ROW)
    data = fix_exprs(data)
    data = set_variables(data)
    data["uid"] = UID
    data.pop("id", None)
    data.pop("version", None)
    data = fix_v1beta1_schema(data)

    with open(OUTPUT, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

    print(f"Generated: sync/K8s/Storage/{os.path.basename(OUTPUT)} from {tag}")


if __name__ == "__main__":
    main()
