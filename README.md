# fleet-dashboards

Grafana dashboards synced via Grafana's [Git Sync](https://grafana.com/docs/grafana/latest/as-code/observability-as-code/git-sync/) feature from `sync/`.

## Adding a dashboard from the Grafana 13 UI

Git Sync needs each file wrapped as a Kubernetes resource
(`apiVersion` / `kind` / `metadata` / `spec`). Grafana's "JSON model" view
gives you only the bare body, which the v2 schema validator rejects.

After pasting a fresh model into `sync/...`, run:

```sh
python3 build/lib/wrap_resource.py
```

It wraps any bare v2-schema dashboard (top-level `elements`) in place.
Legacy `panels`-form dashboards are left alone — the operator still
accepts those bare.

## Other build scripts

- `build/lib/v1beta1_schema.py` — fixes legacy-schema validation issues
  (string-form `datasource` refs, empty `maxDataPoints`).
