"""Exercise snapshot boundaries, the persistent UI store, and query isolation."""

import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from datastore_ui.store import Store, snapshot


def event(number, category='process'):
    kind = 'process_exec' if category == 'process' else 'process_kprobe'
    process = {'pid': number, 'exec_id': f'ui-test:{number}', 'binary': '/nodejs/bin/node'}
    return {'schema_version': 1, 'collector': 'tetragon', 'event_type': kind,
            'timestamp': '2026-10-28T12:00:00Z', 'host': {'name': 'test-host'},
            'category': category, 'process': process, 'container': {'id_prefix': 'a' * 31},
            'file': {'path': '/tmp/fake-credentials', 'permission_mask': 4, 'permission_result': 0} if category == 'file' else None,
            'network': {'destination_ip': '127.0.0.1', 'destination_port': 12345, 'state': 'TCP_SYN_SENT'} if category == 'network' else None,
            'tetragon': {'time': '2026-10-28T12:00:00Z', 'node_name': 'test-host', kind: {'process': process}}}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='runtime-visibility-ui-test-')
        self.root = Path(self.temporary.name)
        self.staging = self.root / 'staging'
        self.staging.mkdir()
        self.source = self.staging / 'events.jsonl'
        self.store = Store(self.staging, self.root / 'data')

    def tearDown(self):
        self.temporary.cleanup()

    def test_snapshot_defers_partial_tail_and_does_not_change_source(self):
        data = json.dumps(event(1)).encode() + b'\n' + json.dumps(event(2)).encode()[:50]
        self.source.write_bytes(data)
        completed = snapshot(self.source, self.root / 'snapshots')
        self.assertEqual(completed.read_bytes(), data.split(b'\n')[0] + b'\n')
        self.assertEqual(self.source.read_bytes(), data)
        self.assertEqual(snapshot(self.source, self.root / 'snapshots'), completed)
        self.assertEqual(completed.stat().st_mode & 0o777, 0o600)

    def test_empty_or_incomplete_only_source_does_not_publish(self):
        for data in (b'', b'{"partial":'):
            self.source.write_bytes(data)
            self.assertIsNone(snapshot(self.source, self.root / 'snapshots'))
        self.assertEqual(list((self.root / 'snapshots').iterdir()), [])

    def test_import_growth_retry_reopen_and_all_category_projection(self):
        events = [event(1), event(2, 'file'), event(3, 'network')]
        self.source.write_text(json.dumps(events[0]) + '\n')
        self.assertEqual(self.store.import_latest()[0]['inserted_rows'], 1)
        self.assertEqual(self.store.import_latest()[0]['inserted_rows'], 0)
        with self.source.open('a') as output:
            for record in events[1:]:
                output.write(json.dumps(record) + '\n')
        self.assertEqual(self.store.import_latest()[0]['inserted_rows'], 2)
        reopened = Store(self.staging, self.root / 'data')
        _, rows, _ = reopened.query('SELECT category, count(*) FROM security_events GROUP BY category ORDER BY category')
        self.assertEqual(rows, [('file', 1), ('network', 1), ('process', 1)])
        _, rows, _ = reopened.query("SELECT file_path, permission_mask, permission_result FROM security_events WHERE category = 'file'")
        self.assertEqual(rows, [('/tmp/fake-credentials', 4, 0)])
        _, rows, _ = reopened.query("SELECT destination_ip, destination_port, socket_state FROM security_events WHERE category = 'network'")
        self.assertEqual(rows, [('127.0.0.1', 12345, 'TCP_SYN_SENT')])
        _, rows, _ = reopened.query('SELECT normalized_event FROM events ORDER BY process_exec_id')
        self.assertEqual([json.loads(row[0]) for row in rows], events)

    def test_malformed_complete_row_is_not_silently_skipped(self):
        self.source.write_text(json.dumps(event(1)) + '\ninvalid JSON\n')
        with self.assertRaisesRegex(ValueError, ':2:'):
            self.store.import_latest()
        self.assertEqual(self.store.query('SELECT count(*) FROM events')[1], [(0,)])
        self.assertEqual(list((self.root / 'data' / 'parquet').glob('*.parquet')), [])

    def test_query_rejects_mutations_multiple_statements_and_local_file_access(self):
        for sql in ('DELETE FROM events', 'CREATE TABLE secret AS SELECT 1',
                    'SELECT 1; SELECT 2', "ATTACH '/tmp/other.duckdb' AS other"):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.store.query(sql)
        secret = self.root / 'secret.txt'
        secret.write_text('not telemetry')
        with self.assertRaises(duckdb.Error):
            self.store.query('SELECT * FROM read_text(?)', [str(secret)])
        self.assertEqual(secret.read_text(), 'not telemetry')

    def test_query_caps_returned_rows(self):
        columns, rows, truncated = self.store.query('SELECT * FROM range(1000) AS t(number)')
        self.assertEqual(columns, ['number'])
        self.assertEqual(len(rows), 500)
        self.assertTrue(truncated)

    def test_query_timeout_does_not_poison_next_query(self):
        with self.assertRaises(duckdb.InterruptException):
            self.store.query('SELECT sum(random()) FROM range(1000000000000)')
        self.assertEqual(self.store.query('SELECT 42')[1], [(42,)])

    def test_lifecycles_pair_execution_and_exit_without_merging_reused_pids(self):
        started = event(1)
        ended = event(1)
        ended['event_type'] = 'process_exit'
        ended['timestamp'] = '2026-10-28T12:00:04Z'
        ended['tetragon'] = {'time': ended['timestamp'], 'node_name': 'test-host',
                            'process_exit': {'process': ended['process'], 'status': 7}}
        reused_pid = event(2)
        reused_pid['process']['pid'] = 1
        missing_exit = event(3)
        missing_start = event(4)
        missing_start['event_type'] = 'process_exit'
        missing_start['tetragon'] = {'time': missing_start['timestamp'], 'node_name': 'test-host',
                                    'process_exit': {'process': missing_start['process'], 'signal': 'SIGKILL'}}
        records = [started, ended, reused_pid, missing_exit, missing_start]
        self.source.write_text(''.join(json.dumps(record) + '\n' for record in records))
        self.store.import_latest()
        _, rows, _ = self.store.query('''SELECT process_exec_id, duration_seconds, exit_status,
            exit_signal, execution_seen, observation FROM process_lifecycles ORDER BY process_exec_id''')
        self.assertEqual(rows, [
            ('ui-test:1', 4.0, 7, None, True, 'Exit observed'),
            ('ui-test:2', None, None, None, True, 'No exit observed'),
            ('ui-test:3', None, None, None, True, 'No exit observed'),
            ('ui-test:4', None, None, 'SIGKILL', False, 'Exit observed')])
        columns, recent, _ = self.store.lifecycles(' WHERE event_time >= ?', ['2026-10-28T12:00:03Z'])
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0][columns.index('duration_seconds')], 4.0)

    def test_lifecycles_separate_hosts_and_missing_execution_ids(self):
        records = [event(1), event(1), event(2), event(3), event(4)]
        records[1]['host']['name'] = 'second-host'
        records[1]['tetragon']['node_name'] = 'second-host'
        for record in records[2:4]:
            record['process']['exec_id'] = ''
        del records[4]['process']['exec_id']
        self.source.write_text(''.join(json.dumps(record) + '\n' for record in records))
        self.store.import_latest()
        self.assertEqual(self.store.query('SELECT count(*) FROM process_lifecycles')[1], [(5,)])

    def test_lifecycle_uses_exported_start_time_and_preserves_missing_status(self):
        record = event(1)
        record['event_type'] = 'process_exit'
        record['process']['start_time'] = '2026-10-28T11:59:57.500Z'
        record['tetragon'] = {'time': record['timestamp'], 'node_name': 'test-host',
                              'process_exit': {'process': record['process']}}
        self.source.write_text(json.dumps(record) + '\n')
        self.store.import_latest()
        self.assertEqual(self.store.query('SELECT duration_seconds, exit_status FROM process_lifecycles')[1], [(2.5, None)])

    def test_lifecycle_query_handles_many_identities_with_long_arguments(self):
        with duckdb.connect(str(self.store.database)) as connection:
            connection.execute('''INSERT INTO events
                SELECT CAST(i AS VARCHAR), TIMESTAMPTZ '2026-11-01 12:00:00Z',
                       1, 'process_exec', 'test-host', 'exec:' || i, repeat('a', 31),
                       json_object('process', json_object('binary', '/nodejs/bin/node',
                           'arguments', repeat('x', 2000) || i))
                FROM range(8000) AS t(i)''')
        columns, rows, _ = self.store.lifecycles()
        self.assertEqual(len(rows), 200)
        self.assertTrue(all(row[columns.index('executable')] == '/nodejs/bin/node' and
                            row[columns.index('observation')] == 'No exit observed' for row in rows))


if __name__ == '__main__':
    unittest.main()
