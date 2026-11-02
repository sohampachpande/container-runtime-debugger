"""Own the local database and publish immutable snapshots of append-only JSONL."""

import hashlib
import os
from pathlib import Path
import tempfile
import threading

import duckdb

from scripts.ingest_events import EVENT_TABLE, ingest_batch


VIEW = '''CREATE OR REPLACE VIEW security_events AS
    SELECT event_id, event_time, event_type, host_name, process_exec_id,
           container_id_prefix,
           coalesce(normalized_event->>'category', CASE
               WHEN event_type IN ('process_exec', 'process_exit') THEN 'process'
               ELSE 'other' END) AS category,
           normalized_event->'process'->>'binary' AS executable,
           normalized_event->'process'->>'arguments' AS arguments,
           normalized_event->'file'->>'path' AS file_path,
           TRY_CAST(normalized_event->'file'->>'permission_mask' AS INTEGER) AS permission_mask,
           TRY_CAST(normalized_event->'file'->>'permission_result' AS INTEGER) AS permission_result,
           normalized_event->'network'->>'destination_ip' AS destination_ip,
           TRY_CAST(normalized_event->'network'->>'destination_port' AS INTEGER) AS destination_port,
           normalized_event->'network'->>'state' AS socket_state,
           normalized_event
    FROM events'''

LIFECYCLES = '''CREATE OR REPLACE VIEW process_lifecycles AS
    WITH grouped AS (
        SELECT host_name, coalesce(nullif(process_exec_id, ''), 'event:' || event_id) AS lifecycle_id,
               any_value(nullif(process_exec_id, '')) AS process_exec_id,
               any_value(container_id_prefix) AS container_id_prefix,
               max(event_time) AS event_time,
               min(event_time) FILTER (WHERE event_type = 'process_exec') AS executed_at,
               max(event_time) FILTER (WHERE event_type = 'process_exit') AS exited_at,
               arg_min(event_id, event_time) AS first_event_id,
               arg_min(event_id, event_time) FILTER (WHERE event_type = 'process_exec') AS execution_event_id,
               arg_max(event_id, event_time) FILTER (WHERE event_type = 'process_exit') AS exit_event_id
        FROM events WHERE event_type IN ('process_exec', 'process_exit')
        GROUP BY host_name, lifecycle_id
    ), details AS (
        SELECT grouped.*,
               context.normalized_event->'process'->>'binary' AS executable,
               context.normalized_event->'process'->>'arguments' AS arguments,
               context.normalized_event->'parent'->>'binary' AS parent_executable,
               coalesce(TRY_CAST(context.normalized_event->'process'->>'start_time' AS TIMESTAMPTZ), executed_at) AS started_at,
               TRY_CAST(exited.normalized_event->'tetragon'->'process_exit'->>'status' AS INTEGER) AS exit_status,
               exited.normalized_event->'tetragon'->'process_exit'->>'signal' AS exit_signal,
               execution_event_id IS NOT NULL AS execution_seen,
               exit_event_id IS NOT NULL AS exit_seen, 'process' AS category
        FROM grouped
        JOIN events AS context ON context.event_id = coalesce(execution_event_id, first_event_id)
        LEFT JOIN events AS exited ON exited.event_id = exit_event_id
    )
    SELECT *, CASE WHEN exited_at >= started_at THEN
               date_diff('microseconds', started_at, exited_at) / 1000000.0
           END AS duration_seconds,
           CASE WHEN exit_seen THEN 'Exit observed' ELSE 'No exit observed' END AS observation
    FROM details'''


def snapshot(source, directory):
    """Copy the initial complete-line prefix; later appends wait for next import."""
    directory.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as capture, tempfile.TemporaryDirectory(dir=directory) as temporary:
        before = os.fstat(capture.fileno())
        remaining = before.st_size
        partial = Path(temporary) / 'capture.jsonl'
        digest = hashlib.sha256()
        rows = 0
        with partial.open('wb') as output:
            while remaining:
                line = capture.readline(remaining)
                remaining -= len(line)
                if not line.endswith(b'\n'):
                    break
                output.write(line)
                digest.update(line)
                rows += bool(line.strip())
        after = os.fstat(capture.fileno())
        if after.st_size < before.st_size or source.stat().st_ino != before.st_ino:
            raise ValueError(f'Staging file was truncated or replaced during capture: {source.name}')
        if not rows:
            return None
        completed = directory / f'{digest.hexdigest()}.jsonl'
        partial.chmod(0o600)
        try:
            os.link(partial, completed)
        except FileExistsError:
            pass
        return completed


class Store:
    """One cached owner per UI process; a lock also serializes browser sessions."""

    def __init__(self, source, directory):
        self.source = Path(source)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / 'events.duckdb'
        self.lock = threading.Lock()
        with duckdb.connect(str(self.database), config={'threads': 1, 'memory_limit': '128MB'}) as connection:
            connection.execute(f'CREATE TABLE IF NOT EXISTS events ({EVENT_TABLE}, PRIMARY KEY (event_id))')
            connection.execute(VIEW)
            connection.execute(LIFECYCLES)

    def import_latest(self):
        results = []
        with self.lock:
            for source in sorted(self.source.glob('*.jsonl')):
                completed = snapshot(source, self.directory / 'captures')
                if completed is not None:
                    results.append(ingest_batch(completed, self.directory / 'parquet', self.database))
        return results

    def lifecycles(self, where='', parameters=None):
        # Bound identities before joining wide JSON payloads. LIMIT after those
        # joins can still exhaust the query budget on historical infrastructure.
        _, keys, _ = self.query('''SELECT host_name,
            coalesce(nullif(process_exec_id, ''), 'event:' || event_id) AS lifecycle_id
            FROM (SELECT * FROM security_events
                  WHERE event_type IN ('process_exec', 'process_exit')) AS processes''' +
            where + ' GROUP BY host_name, lifecycle_id ORDER BY max(event_time) DESC, lifecycle_id LIMIT 200', parameters)
        condition = 'false'
        values = []
        if keys:
            condition = '(host_name, lifecycle_id) IN (' + ','.join('(?,?)' for _ in keys) + ')'
            values = [value for key in keys for value in key]
        return self.query('''SELECT lifecycle_id, executable, parent_executable,
            started_at, exited_at, duration_seconds, exit_status, exit_signal,
            observation, arguments, container_id_prefix, host_name, execution_seen,
            first_event_id, execution_event_id, exit_event_id
            FROM process_lifecycles WHERE ''' + condition +
            ' ORDER BY event_time DESC, lifecycle_id', values)

    def query(self, sql, parameters=None):
        """Return up to 500 rows from one SELECT, with local file access disabled."""
        with self.lock, duckdb.connect(str(self.database), read_only=True, config={
                'threads': 1, 'memory_limit': '128MB', 'enable_external_access': False,
                'autoload_known_extensions': False, 'autoinstall_known_extensions': False}) as connection:
            statements = connection.extract_statements(sql)
            if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                raise ValueError('Enter one SELECT query. Database changes are disabled.')
            timer = threading.Timer(5, connection.interrupt)
            timer.start()
            try:
                result = connection.execute(sql, parameters or [])
                columns = [column[0] for column in result.description]
                rows = result.fetchmany(501)
                return columns, rows[:500], len(rows) > 500
            finally:
                timer.cancel()
                timer.join()
