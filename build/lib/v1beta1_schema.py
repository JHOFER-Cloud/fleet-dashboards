#!/usr/bin/env python3
"""Transforms to make legacy dashboard JSON pass Grafana 13's stricter
dashboard.grafana.app/v1beta1 admission validator.

Two cases:
- string-form .datasource references must be the object form {type, uid}
- maxDataPoints set to "" must be removed (schema wants a number)

Used by the Thanos and Cilium generators, and runnable as a one-shot
sweep across sync/*.json:

    python3 build/lib/v1beta1_schema.py
"""
import json
import os
import sys

# Datasource names we own and whose UID/type we know.
KNOWN_DATASOURCES = {
    "-- Grafana --":    {"type": "grafana",    "uid": "-- Grafana --"},
    "k8_live_hla1":     {"type": "prometheus", "uid": "eef9f89usay9sb"},
    "k8_dev_hla1":      {"type": "prometheus", "uid": "aef9f9k9lvwn4b"},
    "loki_k8_live_hla1": {"type": "loki",      "uid": "eegmz7m03591ce"},
    "loki_k8_dev_hla1":  {"type": "loki",      "uid": "degmx13wdszk0c"},
    "satisfactory-cache": {"type": "postgres", "uid": "satisfactory-cache"},
}


def _infer_type(value):
    """Best-effort type inference for templated datasource references like
    ${DS_PROMETHEUS} or $datasource. Defaults to prometheus."""
    upper = value.upper()
    if "LOKI" in upper:
        return "loki"
    if "POSTGRES" in upper:
        return "postgres"
    return "prometheus"


def _convert_datasource(value):
    if value in KNOWN_DATASOURCES:
        return dict(KNOWN_DATASOURCES[value])
    return {"type": _infer_type(value), "uid": value}


def fix(data):
    """Walk the dashboard tree in-place applying the transforms. Returns
    the same dict for chaining."""
    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("datasource"), str):
                node["datasource"] = _convert_datasource(node["datasource"])
            if node.get("maxDataPoints") == "":
                del node["maxDataPoints"]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return data


def _walk_sync(root):
    """Apply fix() to every .json under <root>/sync/. Only writes files
    whose parsed data structure actually changes — preserves the original
    file's formatting (indent style, unicode escapes, etc.) where no
    semantic change is needed."""
    import copy

    sync_dir = os.path.join(root, "sync")
    changed = 0
    for dirpath, _, filenames in os.walk(sync_dir):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            with open(path) as fh:
                original = json.load(fh)
            modified = copy.deepcopy(original)
            fix(modified)
            if modified == original:
                continue
            with open(path, "w") as fh:
                json.dump(modified, fh, indent=2)
                fh.write("\n")
            changed += 1
            print(f"  fixed: {os.path.relpath(path, root)}")
    print(f"Updated {changed} file(s).")


if __name__ == "__main__":
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _walk_sync(repo_root)
    sys.exit(0)
