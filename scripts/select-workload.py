#!/usr/bin/env python3
"""Select the current Juice Shop container for process telemetry and the UI."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', action='store_true')
    args = parser.parse_args()
    compose = ['docker', 'compose']
    if args.desktop:
        compose += ['-p', 'runtime-visibility-desktop', '-f', 'compose.yaml', '-f', 'compose.desktop.yaml']
    container = subprocess.check_output([*compose, 'ps', '--quiet', 'juice-shop'], text=True).strip()
    if not container:
        parser.exit(1, 'Start juice-shop before selecting the monitored workload.\n')
    details = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
    identity = details['Id']
    if not details['State']['Running'] or re.fullmatch('[a-f0-9]{64}', identity) is None:
        parser.exit(1, 'Expected one running Juice Shop container with a full Docker ID.\n')
    destination = Path(os.environ.get('WORKLOAD_ENV_FILE', '/tmp/runtime-visibility-workload.env'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=destination.parent, delete=False) as output:
        output.write(f'MONITORED_CONTAINER_ID={identity}\n')
        temporary = Path(output.name)
    temporary.replace(destination)
    print(f'Selected juice-shop ({identity[:12]}). Wrote {destination}.')
    print('Recreate Vector and the dashboard with Compose to apply the selection.')


if __name__ == '__main__':
    main()
