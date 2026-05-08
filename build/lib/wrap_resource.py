#!/usr/bin/env python3
"""Wraps bare Grafana v2-schema dashboard JSON (the "JSON model" you copy
out of the Grafana 13 UI) in the Kubernetes resource envelope the Grafana
operator's git-sync requires.

Bare body in -> wrapped resource out:

    {                                {
      "annotations": [...],            "apiVersion": "dashboard.grafana.app/v2",
      "elements": {...},      ->       "kind": "Dashboard",
      ...                              "metadata": {"name": "<basename>"},
    }                                  "spec": { ...original... }
                                     }

Only v2-schema bodies (identified by a top-level `elements` key) are
wrapped — the operator accepts legacy `panels`-form dashboards bare, so
those are left alone to avoid pointless reformat churn. Files that
already have a top-level `apiVersion` are also left alone.

Run as a one-shot sweep across sync/*.json:

    python3 build/lib/wrap_resource.py
"""

import json
import os
import sys


def wrap(body, name):
    """Return the resource-wrapped form of a v2-schema dashboard body with
    metadata.name=`name`."""
    return {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": name},
        "spec": body,
    }


def _walk_sync(root):
    sync_dir = os.path.join(root, "sync")
    wrapped = 0
    for dirpath, _, filenames in os.walk(sync_dir):
        for filename in filenames:
            if not filename.endswith(".json"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path) as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                continue
            if "apiVersion" in data:
                continue
            if "elements" not in data:
                continue
            name = os.path.splitext(filename)[0]
            with open(path, "w") as fh:
                json.dump(wrap(data, name), fh, indent=2)
                fh.write("\n")
            wrapped += 1
            print(f"  wrapped: {os.path.relpath(path, root)}")
    print(f"Wrapped {wrapped} file(s).")


if __name__ == "__main__":
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _walk_sync(repo_root)
    sys.exit(0)
