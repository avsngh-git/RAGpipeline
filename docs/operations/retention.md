# Data retention

`research-maintenance retention` reports eligible records by default. Nothing runs
automatically. Add `--apply` to delete LangGraph checkpoints 7 days after a
completed run, checkpoints 30 days after a failed run, and model-call payload text
after 90 days. Research run rows, tool calls, model-call metadata, claims and
draft claims are retained.

Retired Qdrant points are purged only when both `--collection-name` and
`--configuration` are supplied. The command uses the existing safe purge, which
preserves every point visible to the published generation and unfinished runs.
Failed or unpublished generation points are reported only and are never deleted
by this command, as required by ADR-0026.

Preview the database retention counts:

```bash
research-maintenance retention
```

Preview eligible retired points for a collection and generation configuration:

```bash
research-maintenance retention \
  --collection-name research-papers \
  --configuration configs/index.json
```

Apply database retention and purge eligible retired points:

```bash
research-maintenance retention --apply \
  --collection-name research-papers \
  --configuration configs/index.json
```

Without both Qdrant options, `retired_points` is `null`; database retention still
reports or applies according to `--apply`.
