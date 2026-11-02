"""Storage tests use synthetic normalized events, not claimed live captures."""

import copy
import datetime
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from scripts.ingest_events import VALIDATION_BATCH_ROWS, ingest_batch


def execution(pid=123):
    raw = {'time': '2026-10-27T12:00:00Z', 'node_name': 'test-host',
           'process_exec': {'process': {'pid': pid, 'exec_id': f'test:{pid}',
                                       'binary': '/example/πython', 'arguments': "a'b"}}}
    return {'schema_version': 1, 'collector': 'tetragon',
            'timestamp': '2026-10-27T05:00:00-07:00', 'event_type': 'process_exec',
            'host': {'name': 'test-host'}, 'process': raw['process_exec']['process'],
            'parent': None, 'container': {'id_prefix': None}, 'tetragon': raw}


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="runtime-visibility-'tests-")
        self.root = Path(self.directory.name)
        self.parquet = self.root / 'parquet'
        self.database = self.root / 'events.duckdb'

    def tearDown(self):
        self.directory.cleanup()

    def capture(self, name, events):
        source = self.root / name
        source.write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in events))
        return source

    def ingest(self, source):
        return ingest_batch(source, self.parquet, self.database)

    def test_parquet_and_database_preserve_types_and_original_event(self):
        event = execution()
        event['timestamp'] = '2026-10-27T05:00:00.123456789-07:00'
        event['tetragon']['time'] = '2026-10-27T12:00:00.123456789Z'
        result = self.ingest(self.capture('events.jsonl', [event]))
        self.assertEqual(result['source_rows'], 1)
        self.assertEqual(result['inserted_rows'], 1)
        with duckdb.connect(str(self.database), read_only=True) as connection:
            for relation, parameters in [('events', []), ('read_parquet(?)', [result['parquet']])]:
                row = connection.execute(
                    f"SELECT event_time AT TIME ZONE 'UTC', process_exec_id, container_id_prefix, normalized_event FROM {relation}",
                    parameters).fetchone()
                self.assertEqual(row[0], datetime.datetime(2026, 10, 27, 12, 0, 0, 123456))
                instant = connection.execute(
                    f'SELECT event_time FROM {relation}', parameters).fetchone()[0]
                self.assertEqual(instant, datetime.datetime(
                    2026, 10, 27, 12, 0, 0, 123456, tzinfo=datetime.timezone.utc))
                self.assertEqual(connection.execute(
                    f'SELECT typeof(event_time) FROM {relation}', parameters).fetchone()[0],
                    'TIMESTAMP WITH TIME ZONE')
                self.assertEqual(row[1], 'test:123')
                self.assertIsNone(row[2])
                self.assertEqual(json.loads(row[3]), event)

    def test_same_batch_retry_keeps_published_file_and_rows(self):
        source = self.capture('events.jsonl', [execution()])
        first = self.ingest(source)
        published = Path(first['parquet'])
        identity = published.stat().st_ino, published.stat().st_mtime_ns
        second = self.ingest(source)
        self.assertEqual(second['status'], 'already_imported')
        self.assertEqual(second['inserted_rows'], 0)
        self.assertEqual(identity, (published.stat().st_ino, published.stat().st_mtime_ns))
        self.assertEqual(len(list(self.parquet.glob('*.parquet'))), 1)

    def test_large_capture_validates_and_imports_with_existing_memory_budget(self):
        source = self.root / 'large.jsonl'
        with source.open('w') as output:
            for number in range(16000):
                record = execution(number)
                record['process']['arguments'] = 'x' * 2048
                output.write(json.dumps(record) + '\n')
        result = self.ingest(source)
        self.assertEqual((result['source_rows'], result['inserted_rows']), (16000, 16000))
        self.assertEqual(self.ingest(source)['inserted_rows'], 0)

    def test_row_checksums_detect_changed_metadata_and_duplicate_multiplicity(self):
        for index, change in enumerate(('metadata', 'multiplicity')):
            with self.subTest(change=change):
                first, second = execution(100 + index * 10), execution(101 + index * 10)
                source = self.capture(change + '.jsonl', [first, first, second])
                result = self.ingest(source)
                published = Path(result['parquet'])
                replacement = self.root / (change + '.parquet')
                with duckdb.connect() as connection:
                    connection.read_parquet(str(published)).create('published')
                    if change == 'metadata':
                        connection.execute("UPDATE published SET normalized_event = json_merge_patch(normalized_event, '{\"extra\":\"changed\"}')")
                        rows = connection.table('published')
                    else:
                        rows = connection.sql('''
                            (SELECT DISTINCT * FROM published)
                            UNION ALL
                            SELECT * FROM published WHERE event_id = (
                                SELECT event_id FROM published GROUP BY event_id HAVING count(*) = 1)
                        ''')
                    rows.write_parquet(str(replacement), compression='zstd')
                replacement.replace(published)
                with self.assertRaisesRegex(ValueError, 'content does not match'):
                    self.ingest(source)

    def test_validation_checks_rows_after_first_batch_and_source_order(self):
        source = self.capture('multiple-batches.jsonl',
                              [execution(number) for number in range(VALIDATION_BATCH_ROWS + 3)])
        result = self.ingest(source)
        published = Path(result['parquet'])
        original = published.read_bytes()
        for change in ('last-row', 'order'):
            with self.subTest(change=change):
                published.write_bytes(original)
                replacement = self.root / 'changed.parquet'
                with duckdb.connect() as connection:
                    connection.read_parquet(str(published)).create('published')
                    if change == 'last-row':
                        connection.execute('''UPDATE published
                            SET normalized_event = json_merge_patch(normalized_event, '{"extra":"changed"}')
                            WHERE rowid = ?''', [VALIDATION_BATCH_ROWS + 2])
                        rows = connection.table('published')
                    else:
                        rows = connection.sql('SELECT * FROM published ORDER BY rowid DESC')
                    rows.write_parquet(str(replacement), compression='zstd')
                replacement.replace(published)
                with self.assertRaisesRegex(ValueError, 'content does not match'):
                    self.ingest(source)

    def test_validation_rejects_extra_or_missing_rows(self):
        source = self.capture('row-count.jsonl', [execution(), execution(124)])
        result = self.ingest(source)
        published = Path(result['parquet'])
        original = published.read_bytes()
        for change in ('extra', 'missing'):
            with self.subTest(change=change):
                published.write_bytes(original)
                replacement = self.root / 'changed.parquet'
                with duckdb.connect() as connection:
                    connection.read_parquet(str(published)).create('published')
                    if change == 'extra':
                        rows = connection.sql('SELECT * FROM published UNION ALL SELECT * FROM published LIMIT 3')
                    else:
                        rows = connection.sql('SELECT * FROM published LIMIT 1')
                    rows.write_parquet(str(replacement), compression='zstd')
                replacement.replace(published)
                with self.assertRaisesRegex(ValueError, 'content does not match'):
                    self.ingest(source)

    def test_duplicates_within_and_across_batches_are_deduplicated(self):
        event = execution()
        first = self.ingest(self.capture('one.jsonl', [event, event, execution(124)]))
        reordered = copy.deepcopy(event)
        reordered['tetragon'] = dict(reversed(list(event['tetragon'].items())))
        second = self.ingest(self.capture('two.jsonl', [reordered, execution(125)]))
        self.assertEqual(first['source_rows'], 3)
        self.assertEqual(first['inserted_rows'], 2)
        self.assertEqual(second['inserted_rows'], 1)
        with duckdb.connect(str(self.database), read_only=True) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM events').fetchone()[0], 3)
            self.assertEqual(connection.execute('SELECT count(*) FROM imported_batches').fetchone()[0], 2)

    def test_optional_context_can_be_null(self):
        event = execution()
        event['process'] = None
        event['container'] = None
        self.ingest(self.capture('events.jsonl', [event]))
        with duckdb.connect(str(self.database), read_only=True) as connection:
            self.assertEqual(connection.execute(
                'SELECT process_exec_id, container_id_prefix FROM events').fetchone(), (None, None))

    def test_malformed_row_does_not_publish_or_import_partial_batch(self):
        source = self.capture('events.jsonl', [execution()])
        with source.open('a') as output:
            output.write('not json\n')
        with self.assertRaisesRegex(ValueError, 'events.jsonl:2:'):
            self.ingest(source)
        self.assertFalse(self.database.exists())
        self.assertEqual(list(self.parquet.iterdir()), [])

    def test_rejects_invalid_envelopes_before_publication(self):
        for field, value in [('schema_version', True), ('schema_version', 99),
                             ('timestamp', '2026-10-27T12:00:00'),
                             ('host', {}), ('process', []), ('tetragon', {})]:
            with self.subTest(field=field, value=value):
                event = execution()
                event[field] = value
                with self.assertRaises(ValueError):
                    self.ingest(self.capture('invalid.jsonl', [event]))
        self.assertFalse(self.database.exists())
        self.assertEqual(list(self.parquet.iterdir()), [])

    def test_empty_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no events'):
            self.ingest(self.capture('empty.jsonl', []))
        self.assertFalse(self.database.exists())

    def test_retry_after_publication_but_before_database_creation(self):
        source = self.capture('events.jsonl', [execution()])
        invalid_database = self.root / 'a-directory'
        invalid_database.mkdir()
        with self.assertRaises(duckdb.Error):
            ingest_batch(source, self.parquet, invalid_database)
        self.assertEqual(len(list(self.parquet.glob('*.parquet'))), 1)
        self.assertEqual(self.ingest(source)['inserted_rows'], 1)

    def test_failed_ledger_insert_rolls_back_event_insert(self):
        with duckdb.connect(str(self.database)) as connection:
            connection.execute('''CREATE TABLE imported_batches (
                batch_id VARCHAR PRIMARY KEY, parquet_name VARCHAR,
                source_rows BIGINT CHECK (source_rows < 0), inserted_rows BIGINT,
                imported_at TIMESTAMPTZ DEFAULT current_timestamp
            )''')
        source = self.capture('events.jsonl', [execution()])
        with self.assertRaises(duckdb.ConstraintException):
            self.ingest(source)
        with duckdb.connect(str(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM imported_batches').fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'events'").fetchone()[0], 0)
            connection.execute('DROP TABLE imported_batches')
        self.assertEqual(self.ingest(source)['inserted_rows'], 1)

    def test_corrupt_published_parquet_is_not_silently_reused(self):
        source = self.capture('events.jsonl', [execution()])
        result = self.ingest(source)
        Path(result['parquet']).write_bytes(b'invalid parquet')
        with self.assertRaises(duckdb.Error):
            self.ingest(source)


if __name__ == '__main__':
    unittest.main()
