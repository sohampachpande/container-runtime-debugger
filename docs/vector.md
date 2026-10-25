# Vector event pipeline

## Scope and status

Milestone 4 introduces a pipeline for the already verified Tetragon process
execution and exit events. On 2026-10-25, Vector 0.60.0 was deployed on the VM
from `m4/pipeline`; configuration validation, four transform tests, live event
correlation, and counter-label checks passed. Raw cgroup enrichment is still
deferred. Prometheus scraping and execution of a rate query remain unverified.

```text
/var/log/tetragon/tetragon.log
  → file source with persistent read checkpoints
  → parse and normalize execution/exit events
      → structured JSON on stdout
      → runtime_events_total{host,event_type} on /metrics
  → rejected records on stderr
```

The pinned image is `timberio/vector:0.60.0-alpine`. See the upstream
[Docker installation guide](https://vector.dev/docs/setup/installation/platforms/docker/).
No new APT package, Docker socket access, or privileged container is needed.

## Event and metric choices

The common log envelope contains `schema_version`, `collector`, `timestamp`,
`event_type`, `host`, `process`, `parent`, and `container`. The complete original
JSON object is retained under `tetragon`, including exit status and event-specific
fields. `container.id_prefix` carries Tetragon's truncated Docker identity;
it is not presented as a full container ID. Missing metadata remains null.

Only process execution and exit are normalized in this step. Malformed JSON,
missing required fields, and other event types are routed to the rejection
output instead of counted as valid events. Additional schemas are Milestone 5.
The inline tests cover execution, exit, malformed JSON, and metric-label isolation.

The counter increases once per normalized record and has exactly two labels:
host and event type. PIDs, executable paths, arguments, execution IDs, and
container IDs remain in logs. The counter counts exported records, including
startup-discovered processes; it is not a count of all kernel calls.

A counter supports event-rate queries such as
`rate(runtime_events_total[1m])` when scraped by Prometheus. The exporter alone
does not calculate that query or retain a time series; deploying Prometheus
is outside this step. Exported counters omit event timestamps so Prometheus
can assign scrape time. Counters reset when Vector restarts.

## Permissions, checkpoints, and resource limits

Tetragon retains its root-only log permissions. Vector runs as UID 0 inside
its container to read those files, with all Linux capabilities dropped and
the source log directory mounted read-only. This is a lab permission choice;
a dedicated user with narrowly scoped file access can be evaluated later.

The deployment uses one Vector worker, a provisional 128 MiB container limit,
and loopback port 9598. Its JSON console output is retained in Docker logs
with three 10 MB files. This is bounded demo retention, not durable archival.
Measure actual memory alongside Tetragon and Juice Shop before adding services.

The file source starts at the end on first discovery so the first run does
not replay all previous exercises. A named volume preserves checkpoints on
subsequent runs. It mounts the directory rather than a single file so log
rotation can be followed. Checkpoints are not an exactly-once guarantee;
outages, rotation, and container restarts need further operational testing.

## Validate and run with Compose

The root `compose.yaml` contains Vector alongside Tetragon and Juice Shop.
For development, combine it with `compose.desktop.yaml`. Follow
[the Docker Desktop guide](docker-desktop.md) for configuration validation,
the four Vector tests, startup, logs, and shutdown commands.

The override creates the `runtime-visibility-desktop-vector-data` checkpoint
volume automatically. Vector reads the shared Tetragon log volume read-only.
No separate Vector Compose file or hand-written `docker run` deployment is needed.

## Verify the pipeline

The [Desktop acceptance check](docker-desktop.md#repeat-the-live-acceptance-check)
generates fresh host and Juice Shop executions. Match their host PIDs,
executables, execution IDs, and original event objects between the raw file
and normalized output. Confirm that both event counters advance and that
labels remain limited to `host` and `event_type`.

Use the [Desktop lifecycle commands](docker-desktop.md#inspect-output-and-stop)
to inspect resource use and stop the lab. Compose teardown without `-v`
retains the named event and checkpoint volumes.

The full Compose deployment is verified on Docker Desktop. Run
`python3 scripts/verify-pipeline.py --desktop` for the repeatable acceptance
check. It validates event correlation and counter labels; it does not execute
a Prometheus rate query or test checkpoint recovery.
