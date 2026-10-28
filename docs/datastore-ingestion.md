# Local Parquet and DuckDB ingestion

The initial batch importer is implemented and tested with synthetic normalized
execution records. It accepts the current Tetragon `schema_version: 1` envelope,
not raw Tetragon logs or mixed Docker diagnostics. New file/network field
mapping and live end-to-end validation remain pending. Follow
[the action plan](../plans/milestone-5-datastore-plan.md) and
[the datastore decision](datastore.md).

## What is implemented

1. Vector's `staging` file sink writes normalized execution/exit events to
   `/var/lib/vector/staging/events-%Y-%m-%d.jsonl` in its persistent data volume.
   The updated configuration still needs validation with the pinned Vector image.
2. `scripts/ingest_events.py` validates one completed JSONL file and projects
   explicit column types. It snapshots projected rows into a private temporary
   directory so conversion does not repeatedly read the original file.
3. DuckDB writes Zstandard-compressed Parquet. The source file's SHA-256 names
   the batch. Full row comparison validates the output before atomic publication
   without overwriting an existing batch. A retry validates the existing file.
4. The importer inserts events and a batch ledger record in one transaction.
   Event IDs hash canonical original Tetragon JSON, making key order irrelevant.
   Identical exported records deduplicate within and across batches; this is
   record deduplication, not a promise of one row per unique kernel operation.

Parquet retains the source row count, including repeated records. DuckDB's
`events` table contains unique record IDs. If the same raw record arrives with
different normalized context, the first imported representation is retained.
There is no automatic schema migration or update of already imported rows.

| Column | DuckDB type | Meaning |
|---|---|---|
| `event_id` | VARCHAR, primary key in `events` | SHA-256 of canonical original event JSON |
| `event_time` | TIMESTAMPTZ | Event timestamp converted to UTC |
| `schema_version` | BIGINT | Current supported envelope version: 1 |
| `event_type` | VARCHAR | Collector event type |
| `host_name` | VARCHAR | Exported host name |
| `process_exec_id` | VARCHAR, nullable | Available execution identity |
| `container_id_prefix` | VARCHAR, nullable | Available Docker ID prefix |
| `normalized_event` | JSON | Complete normalized object, including original `tetragon` |

The typed `TIMESTAMPTZ` column has microsecond precision; the original timestamp
string, including any nanoseconds, remains unchanged in `normalized_event`.
Order events with execution identity as well as time when sub-microsecond
ordering matters. TIMESTAMPTZ represents an instant; its display timezone is
controlled by the querying session.

File/network details will remain accessible in preserved JSON while typed
investigation fields are added from verified live schemas. The importer does
not interpret kernel arguments or claim to normalize new event categories.

## 1. Create an isolated Python environment

Run from the repository root in one shell. These commands install only the
pinned DuckDB dependency into a fresh temporary virtual environment; they do
not install host services or change Docker/cloud resources.

```sh
datastore_env=$(mktemp -d /tmp/runtime-visibility-python.XXXXXX)
python3 -m venv "$datastore_env"
"$datastore_env/bin/python" -m pip install -r requirements-datastore.txt
PYTHONDONTWRITEBYTECODE=1 "$datastore_env/bin/python" -m unittest discover -s tests -v
```

Python 3.9 and DuckDB 1.4.1 were used for the offline tests. The dependency
does not install a separate DuckDB database server. Keep these shell variables
available for the following commands.

## 2. Validate and collect normalized output

First finish the policy-loading checks in [the security-event guide](security-events.md).
The commands below validate and test Vector, then update its service so the new
file sink is active. Startup may recreate services to apply pending configuration.
The existing acceptance script only proves execution/exit telemetry.

```sh
docker compose -p runtime-visibility-desktop \
  -f compose.yaml -f compose.desktop.yaml run --rm --no-deps vector \
  validate --no-environment /etc/vector/vector.toml
docker compose -p runtime-visibility-desktop \
  -f compose.yaml -f compose.desktop.yaml run --rm --no-deps vector \
  test /etc/vector/vector.toml
docker compose -p runtime-visibility-desktop \
  -f compose.yaml -f compose.desktop.yaml up --detach vector
python3 scripts/verify-pipeline.py --desktop
```

## 3. Complete and copy a batch

Gracefully stop Vector to close/flush its staging files, copy them into a fresh
local directory, then start Vector again. The copied files are the completed
inputs. Do not convert the live named-volume files while Vector appends to them.
The pause creates an ingestion gap; source rotation during the pause is still
an unverified recovery case. No volumes are removed.

```sh
datastore_data=$(mktemp -d /tmp/runtime-visibility-data.XXXXXX)
printf 'Local data directory: %s\n' "$datastore_data"
docker compose -p runtime-visibility-desktop \
  -f compose.yaml -f compose.desktop.yaml stop --timeout 30 vector
docker compose -p runtime-visibility-desktop \
  -f compose.yaml -f compose.desktop.yaml cp \
  vector:/var/lib/vector/staging/. "$datastore_data/staging"
docker compose -p runtime-visibility-desktop \
  -f compose.yaml -f compose.desktop.yaml up --detach vector
```

Check that the copy succeeded and contains JSONL files. If copying fails,
restart Vector before investigating. Preserve the copied files as immutable
inputs. A date-based filename alone does not make an active file immutable.

## 4. Convert and import

The importer processes one completed file at a time. This loop imports each
copied daily file into the same database. Repeating it should report
`already_imported` with zero newly inserted rows. Keep the source copies.

```sh
for capture in "$datastore_data"/staging/*.jsonl; do
  "$datastore_env/bin/python" scripts/ingest_events.py "$capture" \
    --parquet-dir "$datastore_data/parquet" \
    --database "$datastore_data/events.duckdb" || break
done
```

Run imports serially. Do not open the mutable database in another process while
the importer owns it. If database import fails after Parquet publication, the
Parquet remains available for retry; malformed input does not publish a partial
batch. The command reports counts and paths rather than event contents.

After the importer closes, inspect counts through a read-only connection:

```sh
"$datastore_env/bin/python" - "$datastore_data/events.duckdb" <<'PY'
import sys
import duckdb
with duckdb.connect(sys.argv[1], read_only=True) as connection:
    print(connection.execute('''
        SELECT event_type, host_name, count(*) AS records
        FROM events GROUP BY event_type, host_name
        ORDER BY event_type, host_name
    ''').fetchall())
    print(connection.execute('''
        SELECT count(*) AS batches, sum(source_rows), sum(inserted_rows)
        FROM imported_batches
    ''').fetchall())
PY
```

## Verification and limits

Ten offline tests cover timezone and nanosecond-source timestamp/JSON preservation, missing optional
context, same-batch retries, within/across-batch duplicates, malformed/empty
inputs, unsupported schema versions, post-publication recovery, transactional
rollback, and corrupt published files. Fixtures are synthetic and contain no
production captures. Live Vector/Parquet/DuckDB validation remains pending.

The importer detects ordinary input changes during reading, but cannot establish
that a writer is stopped; completed inputs are a caller requirement. Atomic
publication and transactions are not tested power-loss durability guarantees.
The command does not watch directories, schedule imports, expire data, enforce
a disk quota, or provide an API. JSONL, Parquet, and native tables consume
separate space; retention and operational recovery remain milestone gates.
Keep all three representations outside Git and treat their process arguments
and host context as sensitive.
