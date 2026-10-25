#!/usr/bin/env python3
"""Verify the root Compose pipeline using fresh host and Juice Shop events."""

import datetime
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.DEVNULL)


vector_id = docker('compose', 'ps', '--quiet', 'vector').strip()
juice_id = docker('compose', 'ps', '--quiet', 'juice-shop').strip()
assert vector_id and juice_id, 'Start the root Compose stack before verification'


def samples():
    with urllib.request.urlopen('http://127.0.0.1:9598/metrics', timeout=3) as response:
        text = response.read().decode()
    result = {}
    for line in text.splitlines():
        match = re.match(r'runtime_events_total\{([^}]*)\}\s+([0-9.eE+\-]+)', line)
        if match:
            labels = dict(re.findall(r'(\w+)="([^"]*)"', match[1]))
            assert set(labels) == {'host', 'event_type'}, labels
            result[(labels['host'], labels['event_type'])] = float(match[2])
    return result


for attempt in range(50):
    try:
        before = samples()
        break
    except OSError:
        time.sleep(0.2)
else:
    raise SystemExit('Vector metrics endpoint did not become ready')

started = datetime.datetime.now(datetime.timezone.utc).isoformat()
container = json.loads(docker('inspect', juice_id))[0]
marker = 'compose_pipeline_probe'
expected_raw = {}
with open('/var/log/tetragon/tetragon.log') as source:
    source.seek(0, 2)
    host = subprocess.Popen(['/usr/bin/sleep', '2'])
    docker('exec', '--detach', juice_id, '/nodejs/bin/node', '-e',
           f'setTimeout(() => {{}}, 15000) // {marker}')
    host.wait(timeout=5)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        line = source.readline()
        if not line:
            if {'host_exec', 'host_exit', 'container_exec'}.issubset(expected_raw):
                break
            time.sleep(0.2)
            continue
        event = json.loads(line)
        for event_type, payload in event.items():
            if event_type not in ('process_exec', 'process_exit'):
                continue
            process = payload['process']
            if process['pid'] == host.pid:
                expected_raw['host_exec' if event_type == 'process_exec' else 'host_exit'] = event
            if event_type == 'process_exec' and process.get('binary') == '/nodejs/bin/node' and marker in process.get('arguments', ''):
                prefix = process.get('docker', '')
                assert prefix and container['Id'].startswith(prefix)
                cgroup = Path(f'/proc/{process["pid"]}/cgroup').read_text()
                assert container['Id'] in cgroup
                expected_raw['container_exec'] = event
assert len(expected_raw) == 3, list(expected_raw)

matched = {}
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    for line in docker('logs', '--since', started, vector_id).splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for name, raw in expected_raw.items():
            if event.get('tetragon') == raw:
                kind = 'process_exit' if name == 'host_exit' else 'process_exec'
                assert event['event_type'] == kind
                assert event['process'] == raw[kind]['process']
                assert event['host']['name'] == raw['node_name'] == socket.gethostname()
                if name == 'container_exec':
                    assert event['container']['id_prefix'] == raw[kind]['process']['docker']
                matched[name] = {'host_pid': event['process']['pid'], 'event_type': kind,
                                 'binary': event['process']['binary'],
                                 'container_id_prefix': event['container']['id_prefix']}
    after = samples()
    if len(matched) == 3:
        break
    time.sleep(0.2)
assert len(matched) == 3, matched
for kind in ('process_exec', 'process_exit'):
    key = (socket.gethostname(), kind)
    assert after.get(key, 0) > before.get(key, 0), (kind, before, after)
print(json.dumps({'matched_events': matched, 'counter_deltas': {
    kind: after.get((socket.gethostname(), kind), 0) - before.get((socket.gethostname(), kind), 0)
    for kind in ('process_exec', 'process_exit')},
    'metric_label_keys': ['event_type', 'host']}, indent=2))
