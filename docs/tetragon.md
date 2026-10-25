# Tetragon collector

## Scope and status

Run one Tetragon systemd service on the Ubuntu GCP VM. This first deployment
uses the upstream native package so Docker is not a prerequisite. Dedicated
container packaging remains a later step. No custom tracing policies are needed
for the built-in process-execution events.

On 2026-10-25, Tetragon and tetra v1.7.0 were installed on the GCP VM. The base
sensor loaded and exported a live execution event with a verified host PID and
executable. The event did not include cgroup identity, so Milestone 3 remains
incomplete. See [the recorded evidence](milestone.md#milestone-3-ebpf-event-pipeline-and-process-execution).
Vector normalization belongs to Milestone 4.

No Tetragon source checkout or build toolchain is needed: the upstream package
includes the daemon, CLI, compiled BPF programs, and a working bundled
`bpftool` at `/usr/local/lib/tetragon/bpftool`. The Ubuntu `bpftool` wrapper
remains unusable for this kernel.

The package is pinned to `v1.7.0`, the version used in the upstream
[package installation guide](https://tetragon.io/docs/installation/package/).
Settings use the recommended administrator drop-ins from the
[daemon configuration reference](https://tetragon.io/docs/reference/daemon-configuration/).

## How process collection works

Process execution and exit collection are built into Tetragon's base sensor.
Starting the daemon loads this sensor; no custom tracing policy was needed for
the events we captured. The service journal confirmed
`Loaded sensor successfully` for `__base__`.

```text
systemd starts Tetragon
  → Tetragon loads its built-in base eBPF sensor
  → sensor observes process execution and termination
  → Tetragon adds process, parent, and available container context
  → JSON exporter writes /var/log/tetragon/tetragon.log
```

`process_exec` means a process executed a program. It does not always mean a
new process was created: Linux can replace a process's program through `exec`
while retaining its PID. `process_exit` records termination.

We are not recording every system call. A command such as `cat /etc/hostname`
can open a file, read bytes, write output, and close descriptors. The current
setup observes program execution and exit, not each of those file operations.
One JSON record does not necessarily correspond to one system call.

The `tetragon.conf.d` drop-ins configure daemon and export behavior, including
the JSON filename, permissions, rotation, and API endpoints. We have not set
an export event allowlist, so execution and exit events from the base sensor
are exported. Tetragon's versioned API defines their JSON structure; these
drop-ins do not define a custom event schema.

## Expanding collection with tracing policies

A `TracingPolicy` adds specific observations alongside the base sensor. It
selects a hook point, arguments or return values to capture, optional filters
called selectors, and actions. Tetragon loads and attaches the eBPF programs;
we do not need to write a new general-purpose collector.

Kprobes attach to kernel functions, tracepoints attach to predefined kernel
events, and uprobes attach to userspace functions. Tracepoints generally offer
better portability; kernel function names and signatures can change between
versions. See [hook points](https://tetragon.io/docs/concepts/tracing-policy/hooks/).

```text
Kernel reaches selected hook
  → eBPF captures selected data
  → selectors filter observations in the kernel
  → matching observation is posted as a Tetragon event
  → JSON exporter writes the event
```

The default policy action is `Post`, which emits an event. Policies can also
perform enforcement, but this project remains observation-only. Despite their
Kubernetes-style YAML, policies can be loaded on the standalone VM through
`tetra` or startup policy files. No custom policies have been loaded for our
current demo. See [tracing policies](https://tetragon.io/docs/concepts/tracing-policy/)
and [selectors](https://tetragon.io/docs/concepts/tracing-policy/selectors/).

| Coverage | Possible observations | What to validate |
|---|---|---|
| Files | Open attempts, reads, writes, deletion | Which operation the hook represents and whether it succeeded |
| Network | Connection attempts, acceptance, socket activity | Direction, endpoints, and outcome |
| Privileges and security | Credential changes, capability checks, namespace changes | Attempt, permission check, or completed change |
| OOM | A process selected as an OOM victim | Which field identifies the victim rather than the currently executing process |

These are coverage candidates, not promises about our current installation.
Check available hooks and argument layouts against the VM's kernel and
Tetragon version before adding each policy.

Collection and detection are separate. An observation establishes activity;
a detection interprets it against an expectation, such as an unexpected
destination or access to a sensitive path. Adding a policy does not make all
matching events suspicious.

Expand one focused policy at a time: choose the behavior, select a hook,
generate controlled activity, inspect the raw JSON, verify its meaning and
container identity, then integrate it with Vector. Broad file or network
tracing can increase noise and overhead on the small VM. Vector normalization
remains Milestone 4; further event coverage follows incrementally.

## 1. Connect and check resources

Run from your Mac:

```sh
gcloud compute ssh runtime-visibility \
  --project=container-runtime-visibility \
  --zone=us-west1-b \
  --tunnel-through-iap
```

Run the remaining commands on the VM. Check the running kernel and memory
before installing another host service:

```sh
uname -m
uname -r
test -r /sys/kernel/btf/vmlinux && echo 'BTF available'
stat -fc %T /sys/fs/cgroup
free -m
df -h / /tmp
```

Expect `x86_64`, readable BTF, and `cgroup2fs`. See
[the full preflight](ebpf-collector.md#gcp-collector-host-preflight) if these
checks differ from the recorded environment. BTF alone does not prove the BPF
programs will load. Measure resource pressure before adding the demo or Vector;
do not resize the VM automatically.

## 2. Keep development files in the repository

Keep source, collector configuration, and documentation in
`~/container-runtime-visibility` on both the Mac and VM, using the same
development branch (`m3/ebpf-collector` for this milestone). Do not use a
separate configuration staging directory under the VM's home directory.

For committed changes, use Git to synchronize: commit and push from the
machine where the change was made when ready and authorized, then update the
other checkout. Check for local edits before switching or pulling; reconcile
them rather than overwriting them.

```sh
cd ~/container-runtime-visibility
git status --short --branch
git fetch origin
git switch m3/ebpf-collector
git pull --ff-only
```

The uncommitted milestone files were explicitly copied from the Mac checkout
to the same paths in the VM checkout and verified by SHA-256 hashes. This is
a snapshot transfer, not automatic bidirectional synchronization. Before
transferring further uncommitted work, compare both working trees and agree
which copy is authoritative; do not copy `.git`, Terraform state, credentials,
or runtime captures between machines.

The repository is the source of truth for our configuration. Tetragon still
reads its active configuration from `/etc/tetragon/tetragon.conf.d/`, writes
runtime events under `/var/log/tetragon/`, and uses binaries installed under
`/usr/local/`. These are deployment artifacts, not additional source checkouts.
Updating Git files alone does not apply configuration to the running service.

For a fresh installation, install the repository drop-ins before running the
upstream installer, which starts the service. If Tetragon is already installed,
inspect its active configuration before replacing settings. Run on the VM:

```sh
cd ~/container-runtime-visibility
sudo install -d -m 0755 /etc/tetragon/tetragon.conf.d
sudo install -m 0644 collector/tetragon/tetragon.conf.d/* \
  /etc/tetragon/tetragon.conf.d/
sudo install -d -m 0700 /var/log/tetragon
```

For an existing deployment, restart Tetragon after reviewing and applying
configuration changes, then check the service journal and event export again.

The drop-ins disable Kubernetes lookup, select the JSON event file, restrict
event-file access to root, and retain two rotated 10 MB files plus the active
file. The gRPC endpoint uses a local Unix socket; the health endpoint is bound
to `127.0.0.1:6789`. These settings do not reduce
the memory needed by Tetragon's BPF maps or process cache. Diagnostic service
logs are separate from the JSON events.

## 3. Install and check startup

Download the pinned amd64 package into a fresh temporary directory. Inspect
the bundled installer before executing it as root:

```sh
tetragon_download_dir=$(mktemp -d)
cd "$tetragon_download_dir"
curl --fail --location --remote-name \
  https://github.com/cilium/tetragon/releases/download/v1.7.0/tetragon-v1.7.0-amd64.tar.gz
curl --fail --location --remote-name \
  https://github.com/cilium/tetragon/releases/download/v1.7.0/tetragon-v1.7.0-amd64.tar.gz.sha256sum
sha256sum --check tetragon-v1.7.0-amd64.tar.gz.sha256sum
tar -xzf tetragon-v1.7.0-amd64.tar.gz
cd tetragon-v1.7.0-amd64
less install.sh
sudo ./install.sh
tetra version
sudo systemctl status tetragon --no-pager --full
sudo journalctl -u tetragon -n 100 --no-pager
sudo systemctl show tetragon -p MemoryCurrent -p NRestarts
free -m
```

Success requires a running service, successful sensor loading in its logs,
and actual JSON events in the next step. An active systemd unit alone is
insufficient. If startup fails, retain the journal output and check resource
pressure before changing any settings:

```sh
sudo journalctl -k -n 100 --no-pager
```

Do not repeatedly restart a failing collector or increase VM size without
reviewing the failure. To end the exercise and release collector resources:

```sh
sudo systemctl stop tetragon
```

The upstream installer enables the service on boot. Stopping it ends the
current run; `sudo systemctl disable tetragon` also prevents automatic startup.

## 4. Capture a live process execution

Wait for `Listening for events...` in the service journal before starting the
probe. After successful startup, run this on the VM in the same interactive shell.
The background process stays alive for five minutes so `/proc` can be inspected:

```sh
/usr/bin/sleep 300 &
probe_pid=$!
printf 'Expected host PID: %s\n' "$probe_pid"
readlink "/proc/$probe_pid/exe"
cat "/proc/$probe_pid/cgroup"
ps -p "$probe_pid" -o pid,comm,args
sudo tail -n 100 /var/log/tetragon/tetragon.log
```

Find the `process_exec` record whose `process.pid` matches `probe_pid` and whose
`process.binary` identifies `sleep`. Require execution flags such as
`execve clone`: a record flagged `procFS` reflects startup discovery of an
existing process and does not prove a new execution was observed.
Inspect the full record, including any
workload or cgroup fields, rather than assuming a cgroup field exists. If it
has not appeared yet, follow the file with
`sudo tail -f /var/log/tetragon/tetragon.log` and stop following with Ctrl-C.

The `/proc/<pid>/cgroup` entry is independent host evidence of cgroup membership;
it does not prove that the JSON event contains that identity. If the event
lacks cgroup identity, record that gap and choose enrichment only after
reviewing the actual schema. This host-process probe establishes collection;
demo-container attribution remains a later validation.

Let the probe exit naturally. Keep raw events on the VM: command arguments and
host metadata may contain sensitive data. Share only the probe's redacted event,
expected PID, executable, and cgroup entry. Record the Tetragon version, kernel,
startup result, and measured memory use in `docs/milestone.md` after validation.

## 5. Test Docker container identity

The current workload is OWASP Juice Shop. The Compose plugin is not installed
on this VM, so the verified deployment uses Docker directly with the same
image, memory limit, and port mapping as `compose.yaml`. The following commands
assume the container name and port are unused. Reuse the running container if
it already exists.

```sh
cd ~/container-runtime-visibility
sudo docker pull bkimminich/juice-shop:v20.3.0
sudo docker run --detach --name juice-shop-m3 --memory=384m \
  --publish 127.0.0.1:3000:3000 bkimminich/juice-shop:v20.3.0
```

Once the app has started, verify HTTP readiness and identify its main process:

```sh
curl --fail --silent --output /dev/null http://127.0.0.1:3000/
sudo docker inspect juice-shop-m3 \
  --format 'ID={{.Id}} HostPID={{.State.Pid}} MemoryLimit={{.HostConfig.Memory}}'
sudo docker top juice-shop-m3 -eo pid,args
sudo docker stats --no-stream juice-shop-m3
sudo tail -n 30 /var/log/tetragon/tetragon.log
```

Match the Node.js startup execution's host PID to Docker's main process PID.
The event should include `process.docker`, matching a prefix of Docker's full
container ID. Do not assume a fixed prefix length. Inspect the actual event
rather than expecting the Python executable used by the original demo.

While the process is alive, inspect `/proc/<host-pid>/cgroup` and compare its
membership with the container ID. This VM uses systemd
`docker-<full-container-id>.scope` cgroups. The earlier Python startup and
`docker exec` sleep test also established that Tetragon distinguishes the
container's init tree (`in_init_tree: true`) from an injected execution
(`false`). See [the milestone evidence](milestone.md) for both tests.

The test proves native Docker container identity without a custom resolver.
It does not prove raw cgroup identity is exported: that field is still absent.
The original Python OOM exercise remains in `compose.oom.yaml`; Juice Shop
does not provide its `/healthz` or `/allocate` endpoints. Run one demo workload
at a time on the small VM.
