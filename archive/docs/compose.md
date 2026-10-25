# Compose lab deployment

## Scope and verification status

The root `compose.yaml` declares three separate containers: Tetragon, Vector,
and Juice Shop. Versions, mounts, resource limits, loopback ports, and bounded
Docker logs are defined in the repository. Vector's transform configuration
and four tests have already passed using its pinned image. The root
Compose configuration was validated and all three services were started on
the VM on 2026-10-25. Containerized Tetragon loaded its base sensor; fresh host
and Juice Shop events passed the repository acceptance check.

The default root file targets the Ubuntu Linux VM. For a full local test using
Docker Desktop's Linux kernel, use [the Desktop override](../../docs/docker-desktop.md).
Tetragon's privileged container
uses host PID, cgroup, and UTS namespaces plus the host's BTF metadata. Its
eBPF programs execute in that host kernel and observe host and container
activity. UTS sharing preserves the host name in exported events. This follows
the upstream [container deployment](https://tetragon.io/docs/installation/container/).
Do not run two collectors on the same node.

| Service | Memory limit | Output and access |
|---|---|---|
| `tetragon` | 256 MiB, provisional | Raw JSON in host `/var/log/tetragon/tetragon.log`; no published API port |
| `vector` | 128 MiB | Normalized JSON on stdout; rejected records on stderr; metrics at `127.0.0.1:9598/metrics` |
| `juice-shop` | 384 MiB | Application at `127.0.0.1:3000` |

Tetragon mounts repository drop-ins read-only, so it does not inherit the
native package's `/usr/local/lib` configuration. Vector mounts the log directory
read-only and keeps all process/workload detail in logs rather than metric
labels. Runtime data stays outside Git.

## Repository

Keep the Mac and VM checkouts on the same development branch (`m4/pipeline`
for this step). Check `git status` on both before syncing. Once changes are
committed and pushed with approval, update the other clean checkout using
`git pull --ff-only`. Uncommitted development snapshots must be copied
explicitly and compared; this does not provide automatic bidirectional sync.
Keep credentials, Terraform state, raw captures, and checkpoint data outside
that transfer. Updating repository files does not restart running containers.

## 1. Host prerequisites

Run on a Linux host from the repository root. Docker Engine and the Compose
plugin are prerequisites. Our Ubuntu VM has Docker and
`docker-compose-v2` version `2.40.3+ds1-0ubuntu1~24.04.1` installed. On a fresh
Ubuntu host, install the missing plugin after approval:

```sh
sudo apt-get update
sudo apt-get install -y --no-install-recommends docker-compose-v2
sudo docker compose version
```

During VM setup, refreshing package indexes failed for the unrelated GitHub
CLI repository because its signing key was missing. Compose installed from
the existing signed Ubuntu indexes; no repository trust settings were changed.
That GitHub repository issue remains unresolved.

Prepare the persistent paths. `docker volume create` reuses an existing volume;
the root Compose file references `vector-m4-data` as external storage for read
checkpoints. The same command initializes it on a fresh host. It is not removed
by Compose teardown.

```sh
cd ~/container-runtime-visibility
test -r /sys/kernel/btf/vmlinux
stat -fc %T /sys/fs/cgroup
free -m
sudo install -d -m 0700 /var/log/tetragon
sudo docker volume create vector-m4-data
sudo docker compose config --quiet
sudo docker compose pull
sudo docker compose run --rm --no-deps vector \
  validate --no-environment /etc/vector/vector.toml
sudo docker compose run --rm --no-deps vector test /etc/vector/vector.toml
```

These validation commands do not start Tetragon or Juice Shop. The root
Compose file is the deployment entry point; no native Tetragon installation
is required.

## 2. Start and inspect

Start the three containers using the root file:

```sh
sudo docker compose up --detach
sudo docker compose ps
sudo docker compose logs --follow vector
sudo docker compose logs --tail 100 tetragon
sudo docker compose stats --no-stream
curl --fail --silent --output /dev/null http://127.0.0.1:3000/
curl --fail http://127.0.0.1:9598/metrics
sudo tail -f /var/log/tetragon/tetragon.log
```

Before generating test activity, require `Loaded sensor successfully` for
`__base__` and `Listening for events...` in Tetragon's diagnostic logs, plus
Vector reporting that it is watching the source file. Compose `depends_on`
orders process startup; it does not prove sensor or file-tail readiness.
The pipeline does not guarantee capture of every event during startup.

Press Ctrl-C to stop following logs. `logs tetragon` shows collector diagnostics;
its raw structured events remain in the host file. Stop containers and the
Compose network with `sudo docker compose down`. This retains the raw event
directory and external checkpoint volume. No automatic restart policy is set;
start the stack explicitly after reboot.

The collector requires a Linux kernel. The Desktop override uses the one in
Docker Desktop's VM. To run only Juice Shop on macOS, select the independent
service: `docker compose up --detach juice-shop`.

## 3. Verify host and container telemetry

Run the repository acceptance check after the collector and pipeline are ready:

```sh
sudo python3 scripts/verify-pipeline.py
```

It uses the running Compose service IDs, generates a short host process and a
harmless Node.js process inside Juice Shop, compares original and normalized
events, checks container identity against the live cgroup, verifies the host
name, and requires counter increments with exactly two label keys. It prints
a compact result and exits nonzero if a check fails. It requires Python's
standard library and Docker access. Raw logs and `/proc` are read through
the collector container. On Docker Desktop, use the documented `--desktop`
mode so its host probe executes in the Linux VM rather than on macOS.

For manual inspection, the equivalent activity and output commands are:

After both collector and pipeline are ready, record counters, generate a host
probe and a container probe, then inspect their fresh records:

```sh
curl --fail --silent http://127.0.0.1:9598/metrics
/usr/bin/sleep 30 &
probe_pid=$!
printf 'Expected host PID: %s\n' "$probe_pid"
sudo docker compose exec --detach juice-shop /nodejs/bin/node \
  -e 'setTimeout(() => {}, 30000) // compose_pipeline_probe'
sudo docker compose top juice-shop
sudo docker compose logs --since 1m vector
sudo tail -n 100 /var/log/tetragon/tetragon.log
curl --fail --silent http://127.0.0.1:9598/metrics
```

Match the host PID in the raw and normalized events. For the Node.js probe,
match the unique argument marker and confirm that `process.docker` is a prefix
of `sudo docker compose ps --quiet juice-shop` and that the live host process
belongs to its cgroup. Both counters must advance with only `host` and
`event_type` labels. Background host activity also contributes to these
counters; the delta need not equal the number of explicit probes.

Record actual memory and health after startup. Limits are provisional and
do not imply the host can sustain every service at its limit simultaneously.
Prometheus scraping/rate queries and raw cgroup enrichment remain separate work.

## Verified evidence

On 2026-10-25, configuration validation and all four Vector tests passed through
Compose. The acceptance script matched host PID `11020` (`/usr/bin/sleep`)
for execution and exit, and Juice Shop PID `11040` (`/nodejs/bin/node`). The
counter deltas were 7 execution and 7 exit records, including other host
activity. A second `docker compose up --detach` left all three services running.

Exactly one Tetragon process was active. All three containers had
`OOMKilled=false` and zero automatic restarts, Juice Shop HTTP readiness
passed, and the checkpoint volume remained `vector-m4-data`. Measured memory
was about 65 MiB for Tetragon, 23 MiB for Vector, and 108 MiB for Juice Shop;
the host had about 275 MiB available. These are point-in-time observations.
Restart/checkpoint recovery and log rotation are not yet acceptance-tested.
