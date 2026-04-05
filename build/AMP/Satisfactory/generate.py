#!/usr/bin/env python3
"""
Generate Grafana dashboards from upstream featheredtoast/satisfactory-monitoring.
- Clones the upstream repo at the commit pinned in satisfactory-monitoring.version
- Replaces datasource UIDs to match local configuration
- Adds satisfactory_frm_ prefix to all Prometheus metric names:
  - In PromQL expressions (metric names before '{')
  - In label_values() calls (variable queries/definitions)
  - In byName matcher options (fieldConfig overrides)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(SCRIPT_DIR, "satisfactory-monitoring.version")
UPSTREAM_URL = "https://github.com/featheredtoast/satisfactory-monitoring"
OUTPUT = os.path.join(SCRIPT_DIR, "..", "..", "..", "sync", "AMP", "Satisfactory")

# String replacements applied to all string values
STRING_REPLACEMENTS = {
    "http://fakeserver:8080": "http://amp-p1.vm-ct.hla1.jhofer.lan:38080",
    "http://frm-server:8080": "http://amp-p1.vm-ct.hla1.jhofer.lan:38080",
    "http://192.168.2.97:8080": "http://amp-p1.vm-ct.hla1.jhofer.lan:38080",
    "img/icons/satisfactory/location-": "img/icons/unicons/location-",
    # dropPod: upstream uses wrong JSON keys, actual data has RequiredItem/RequiredPower
    "data ->> 'RepairItem'": "data -> 'RequiredItem' ->> 'Name'",
    "data ->> 'RepairAmount'": "data -> 'RequiredItem' ->> 'Amount'",
    "data ->> 'PowerRequired'": "data ->> 'RequiredPower'",
}

# Datasource UID replacements: upstream UID -> local UID
DATASOURCE_UIDS = {
    "PBFA97CFB590B2093": "eef9f89usay9sb",  # Prometheus (live)
    "GhzMNppVk": "satisfactory-cache",  # PostgreSQL (frmcache)
}

# Metric name immediately before '{' in PromQL (expr fields, variable queries)
METRIC_SELECTOR_RE = re.compile(
    r"(?<![a-zA-Z0-9_])(?!satisfactory_frm_)([a-z][a-z0-9_:]+)(?=\{)"
)

# Metric name as first argument to label_values() in two-argument form:
# label_values(metric_name, label) or label_values(metric_name{...}, label)
# Single-argument form label_values(label_name) must NOT be matched.
LABEL_VALUES_RE = re.compile(
    r"(?<=label_values\()(?!satisfactory_frm_)([a-z][a-z0-9_:]+)(?=[,{])"
)


def prefix_metrics(s):
    s = METRIC_SELECTOR_RE.sub(r"satisfactory_frm_\1", s)
    s = LABEL_VALUES_RE.sub(r"satisfactory_frm_\1", s)
    return s


def clone_at_commit(commit_sha):
    tmpdir = tempfile.mkdtemp(prefix="satisfactory-monitoring-")
    subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", tmpdir, "remote", "add", "origin", UPSTREAM_URL],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", tmpdir, "fetch", "--depth=1", "origin", commit_sha],
        check=True,
    )
    subprocess.run(
        ["git", "-C", tmpdir, "checkout", "FETCH_HEAD"],
        check=True,
        capture_output=True,
    )
    return tmpdir


COLLAPSED_ROWS = {"Info"}

# Height increase per dashboard map panel (power excluded intentionally)
MAP_HEIGHT_DELTA = {
    "players": 10,
    "dropPod": 12,
    "efficiencyMap": 18,
    "drone": 15,
    "factoryProd": 7,
    "storage": 15,
    "vehicles": 15,
    "train": 6,
}


def resize_map(panels, dashboard):
    delta = MAP_HEIGHT_DELTA.get(dashboard)
    if not delta:
        return panels

    geomap = next((p for p in panels if p.get("type") == "geomap"), None)
    if not geomap:
        return panels

    map_y = geomap["gridPos"]["y"]
    map_h = geomap["gridPos"]["h"]
    map_w = geomap["gridPos"]["w"]
    new_h = map_h + delta

    result = []
    for p in panels:
        gp = p["gridPos"]

        if p.get("type") == "geomap":
            p = {**p, "gridPos": {**gp, "h": new_h}}
        elif map_w == 24:
            # Standalone: shift everything below the map down
            if gp["y"] >= map_y + map_h:
                p = {**p, "gridPos": {**gp, "y": gp["y"] + delta}}
        else:
            # Shared row: panel beside the map
            if map_y <= gp["y"] < map_y + map_h and gp["x"] != geomap["gridPos"]["x"]:
                if dashboard == "train" and p.get("title") == "$train timetable":
                    # Expand timetable to fill remaining height beside map
                    next_stop_h = next(
                        (
                            q["gridPos"]["h"]
                            for q in panels
                            if q.get("title") == "Next stop"
                        ),
                        3,
                    )
                    p = {**p, "gridPos": {**gp, "h": new_h - next_stop_h}}
                elif dashboard != "train":
                    p = {**p, "gridPos": {**gp, "h": new_h}}
            # Shift panels below the original map row down
            elif gp["y"] >= map_y + map_h:
                p = {**p, "gridPos": {**gp, "y": gp["y"] + delta}}

        result.append(p)
    return result


SORT_COLUMNS = ["count", "rate", "amount"]
SORT_COLUMN_RE = re.compile(
    r"\bas\s+(" + "|".join(SORT_COLUMNS) + r")\b", re.IGNORECASE
)


def patch_player_layers(panel):
    if panel.get("type") != "geomap":
        return panel
    layers = panel.get("options", {}).get("layers", [])
    new_layers = []
    changed = False
    for layer in layers:
        if layer.get("filterData", {}).get("options") in ("OnlineDead", "Offline"):
            config = layer.get("config", {})
            layer = {**layer, "config": {**config, "style": {**config.get("style", {}), "opacity": 0.9}}}
            changed = True
        new_layers.append(layer)
    if not changed:
        return panel
    return {**panel, "options": {**panel.get("options", {}), "layers": new_layers}}


def patch_looted_layer(panel):
    if panel.get("type") != "geomap":
        return panel
    layers = panel.get("options", {}).get("layers", [])
    new_layers = []
    changed = False
    for layer in layers:
        if layer.get("filterData", {}).get("options") == "Looted":
            style = layer.get("config", {}).get("style", {})
            new_style = {
                **style,
                "color": {**style.get("color", {}), "fixed": "green"},
                "opacity": 0.9,
                "size": {**style.get("size", {}), "fixed": 8},
                "symbol": {
                    "fixed": "img/icons/unicons/location-point.svg",
                    "mode": "fixed",
                },
            }
            layer = {**layer, "config": {**layer.get("config", {}), "style": new_style}}
            changed = True
        new_layers.append(layer)
    if not changed:
        return panel
    return {**panel, "options": {**panel.get("options", {}), "layers": new_layers}}


def apply_table_sort(panel):
    if panel.get("type") != "table":
        return panel
    sql = " ".join(t.get("rawSql", "") for t in panel.get("targets", []))
    m = SORT_COLUMN_RE.search(sql)
    if not m:
        return panel
    col = m.group(1).lower()
    return {
        **panel,
        "options": {
            **panel.get("options", {}),
            "sortBy": [{"desc": True, "displayName": col}],
        },
    }


def filter_panels(panels):
    return [
        p
        for p in panels
        if p.get("type") != "alertlist"
        and not (p.get("type") == "row" and p.get("title") == "Alerts")
    ]


def collapse_rows(panels):
    result = []
    collecting_into = None  # row panel currently collecting children
    for p in panels:
        if p.get("type") == "row":
            collecting_into = None
            if p.get("title") in COLLAPSED_ROWS:
                collecting_into = {**p, "collapsed": True, "panels": []}
                result.append(collecting_into)
            else:
                result.append(p)
        elif collecting_into is not None:
            collecting_into["panels"].append(p)
        else:
            result.append(p)
    return result


def walk(obj):
    if isinstance(obj, dict):
        if obj.get("uid") in DATASOURCE_UIDS:
            obj["uid"] = DATASOURCE_UIDS[obj["uid"]]
        # byName matchers reference the full metric name without '{}'
        if obj.get("id") == "byName" and isinstance(obj.get("options"), str):
            options = obj["options"]
            if not options.startswith("satisfactory_frm_"):
                obj = {**obj, "options": f"satisfactory_frm_{options}"}
        return {
            k: (
                prefix_metrics(v)
                if k in ("expr", "definition") and isinstance(v, str)
                else (
                    prefix_metrics(v)
                    if k == "query" and isinstance(v, str)
                    else walk(v)
                )
            )
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [walk(v) for v in obj]
    elif isinstance(obj, str):
        for old, new in STRING_REPLACEMENTS.items():
            obj = obj.replace(old, new)
    return obj


def main():
    with open(VERSION_FILE) as fh:
        commit_sha = fh.read().strip()

    print(f"Cloning {UPSTREAM_URL} at {commit_sha[:12]}...")
    tmpdir = clone_at_commit(commit_sha)

    try:
        upstream = os.path.join(tmpdir, "grafana", "dashboards")
        os.makedirs(OUTPUT, exist_ok=True)

        dashboard_files = sorted(f for f in os.listdir(upstream) if f.endswith(".json"))
        if not dashboard_files:
            print(
                f"ERROR: No dashboard JSON files found in {upstream}", file=sys.stderr
            )
            sys.exit(1)

        for name in dashboard_files:
            dashboard = name.replace(".json", "")
            with open(os.path.join(upstream, name)) as fh:
                data = json.load(fh)

            data = walk(data)
            if "panels" in data:
                data["panels"] = filter_panels(data["panels"])
                data["panels"] = collapse_rows(data["panels"])
                data["panels"] = [apply_table_sort(p) for p in data["panels"]]
                data["panels"] = [patch_looted_layer(p) for p in data["panels"]]
                data["panels"] = [patch_player_layers(p) for p in data["panels"]]
                data["panels"] = resize_map(data["panels"], dashboard)
            if "satisfactory-specifics" not in data.get("tags", []):
                data["tags"] = data.get("tags", []) + ["satisfactory-specifics"]
            data["links"] = [
                l for l in data.get("links", []) if l.get("type") != "dashboards"
            ] + [
                {
                    "asDropdown": False,
                    "icon": "external link",
                    "includeVars": False,
                    "keepTime": True,
                    "tags": ["satisfactory"],
                    "targetBlank": False,
                    "title": "General",
                    "tooltip": "",
                    "type": "dashboards",
                    "url": "",
                },
                {
                    "asDropdown": True,
                    "icon": "external link",
                    "includeVars": False,
                    "keepTime": True,
                    "tags": ["satisfactory-specifics"],
                    "targetBlank": False,
                    "title": "Specifics",
                    "tooltip": "",
                    "type": "dashboards",
                    "url": "",
                },
            ]

            dst = os.path.join(OUTPUT, name)
            with open(dst, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")

            print(f"Generated: sync/AMP/Satisfactory/{name}")
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
