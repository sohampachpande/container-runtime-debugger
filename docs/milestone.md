# Milestones

## Milestone 1: Docker OOM debugging demo — complete

The demo Python service runs in a container with a 64 MiB memory limit. A 1 GiB allocation request causes the Linux kernel to kill the process.

**Verified evidence**

- Application logs show allocation progress until termination.
- Docker reports OOMKilled=true and exit code 137.
- Docker reports an applied memory limit of 64 MiB.

See [the debugging workflow](debugging-workflow.md).

## Milestone 2: Linux test environments

The project was cloned to a Raspberry Pi 5, where Docker Compose reproduced and
diagnosed the memory-constrained OOM kill. See [the Raspberry Pi setup](linux-host-setup.md).

**Raspberry Pi status**

1. Docker Compose starts the demo service.
2. The health endpoint responds successfully.
3. The 1 GiB allocation request reproduces the OOM kill.
4. The cgroup v2 memory controller is enabled with cgroup_enable=memory.
5. The running Raspberry Pi kernel does not expose BTF:
   `CONFIG_DEBUG_INFO_BTF` is unset and `/sys/kernel/btf/vmlinux` is absent.

The Pi remains useful for the Docker OOM demo but is not the current Tetragon
test host.

**GCP collector test host — verified**

1. Terraform provisions an Ubuntu 24.04 `e2-micro` VM in `us-west1-b`.
2. The running kernel exposes `/sys/kernel/btf/vmlinux` and enables
   `CONFIG_DEBUG_INFO_BTF=y` and `CONFIG_DEBUG_INFO_BTF_MODULES=y`.
3. The host uses cgroup v2 with the memory controller enabled.
4. IAP SSH and passwordless sudo work.

See [the Terraform lab setup](../terraform/README.md).

**Preflight result**

The BTF, cgroup, process-exec tracepoint, and OOM tracepoint checks pass. The
installed GCP kernel tools do not include a usable `bpftool` binary, so its
feature probe is unavailable on this Ubuntu image. This is not a blocker for
Milestone 3: Tetragon startup is the functional check that its CO-RE programs
can load on this host.

## Milestone 3: eBPF event pipeline and process execution

Deploy Tetragon as the host-level collector described in [the eBPF collector design](ebpf-collector.md). Its first event source is process execution.

**Success criteria**

1. Tetragon starts successfully on the GCP Linux host.
2. A process execution produces one Tetragon JSON event with host PID, process name, and cgroup identity.
3. The event is written to the collector's JSON output stream.

**Implementation status — partially verified on 2026-10-25**

The [Tetragon guide](tetragon.md) and
[`collector/tetragon/tetragon.conf.d/`](../collector/tetragon/tetragon.conf.d/)
provide pinned package installation, local JSON export with log rotation, and
a live host-process probe.

1. Installed Tetragon and tetra `v1.7.0` from the upstream amd64 package after
   verifying its SHA-256 checksum. Bundled `bpftool v7.3.0` is usable at
   `/usr/local/lib/tetragon/bpftool`; the Ubuntu wrapper remains unusable.
2. The `__base__` BPF sensor loaded on kernel `7.0.0-1014-gcp`. The service is
   enabled on boot and running with zero automatic restarts. A deliberate
   restart applied the loopback health endpoint configuration.
3. After that restart, measured service memory was about 57 MiB, with a 132 MiB
   peak; host available memory was about 449 MiB. These are point-in-time
   observations, not a capacity guarantee for the demo and Vector together.
4. A fresh `/usr/bin/sleep 60` execution at `2026-10-25T17:48:56Z` produced a
   `process_exec` JSON record with PID `4268` and flags `execve clone`. The PID
   and executable matched the live process under `/proc`. The earlier startup
   probe was flagged `procFS` and was excluded as proof of new execution.
5. The JSON export is root-readable at `/var/log/tetragon/tetragon.log`. The
   matching raw probe record is retained only on the VM at
   `/var/log/tetragon/m3-probe.json`. gRPC uses a Unix socket and the health
   endpoint listens on `127.0.0.1:6789`.

**Remaining gap**

The captured execution record has no cgroup field. Its host cgroup membership
was independently checked through `/proc/4268/cgroup` while the process was
alive, but a `/proc` lookup alone does not satisfy criterion 2. Choose an
enrichment approach from the actual schema before completing this milestone.
Vector has not been validated. The Docker probe below verifies native container
identity, but still does not export a raw cgroup field.

**Docker attribution probe — verified on 2026-10-25**

1. Built the existing `demo-app/Dockerfile` as `runtime-visibility-demo-app:m3`
   and started `demo-app-m3` with a 64 MiB limit and port 8080 bound to loopback.
   Docker Compose is unavailable on this VM, so the test used Docker directly.
   The health endpoint returned `ok`; no OOM request was made.
2. The application startup event at `2026-10-25T17:58:59Z` identified host PID
   `4707`, `/usr/local/bin/python`, arguments `app.py`, and `in_init_tree: true`.
3. A `docker exec` probe at `2026-10-25T17:59:28Z` identified host PID `4851`,
   `/bin/sleep`, arguments `120`, and `in_init_tree: false`.
4. Both events included `process.docker: c1813a7ce3b4031489d42bb553af5ad`, a
   prefix matching Docker's full container ID. Docker confirmed the host PIDs;
   `/proc/<pid>/cgroup` confirmed both processes belonged to that container's
   `docker-<full-container-id>.scope` cgroup.
5. Native container identity therefore works without custom enrichment. Neither
   event contains a raw cgroup ID/path or a human-readable container name.
   The matching raw records remain only on the VM at
   `/var/log/tetragon/m3-container-probe.json`.

**Juice Shop workload switch — verified on 2026-10-25**

1. The default `compose.yaml` now selects `bkimminich/juice-shop:v20.3.0`,
   loopback port 3000, and a 384 MiB memory limit. The Python exercise remains
   available separately through `compose.oom.yaml` with its 64 MiB limit.
2. On the VM, stopped `demo-app-m3` and started `juice-shop-m3` using equivalent
   Docker CLI settings because Compose is not installed. HTTP `/` responded
   successfully, `OOMKilled=false`, and measured container memory was about
   136 MiB. Host available memory was about 245 MiB; no VM resize was made.
3. The raw Tetragon log contains a startup event at `2026-10-25T18:23:53Z` for
   host PID `5638`, `/nodejs/bin/node`, arguments `/juice-shop/build/app.js`,
   effective UID `65532`, and `in_init_tree: true`. Its `docker` prefix
   `2118c7fcf4cda7e96eb5baba0ebad80` matched Docker's container ID; the live
   `/proc/5638/cgroup` path independently confirmed membership.
4. Tetragon remained active with zero automatic restarts. The raw cgroup
   export gap remains; no custom tracing policies or Vector pipeline were
   added by this workload switch.

## Milestone 4: Vector event pipeline

Route Tetragon events through Vector and derive low-cardinality event-rate metrics.

**Success criteria**

1. Vector receives structured events from Tetragon.
2. Vector outputs normalized events and an event-rate metric.
3. Metric labels exclude high-cardinality fields such as PID and raw file paths.

## Milestone 5: Collector event coverage and container attribution

Make the pipeline able to process every event schema emitted by the collector without adding event-specific pipeline logic. Expand collector coverage incrementally, beginning with OOM victims and then file-access patterns.

**Success criteria**

1. Process execution events identify the current Juice Shop demo workload.
2. OOM events identify the victim process and, when available, the affected container.
3. File-access events include the accessing process, target path, and available workload identity.
4. Vector handles process execution, OOM, and file-access events through the same normalized event pipeline.
5. The output includes cgroup identity and container identity when available.

**Future security coverage**

Additional event types are intentionally TBD after OOM and file-access patterns are validated. Candidates include process exit, outbound connections, and privilege-related activity.

## Milestone 6: Agent packaging

Package the agent as a dedicated Docker image and prepare a Kubernetes DaemonSet manifest.

**Success criteria**

1. The agent image observes host events without being embedded in application images.
2. The DaemonSet schedules one agent per eligible Kubernetes node.
3. The manifest documents its host mounts and required capabilities.

## Future work

### Platform-backed anomaly detection

Evaluate a search and analytics platform, beginning with OpenSearch, for raw-event retention and statistical anomaly scoring.

**Success criteria**

1. The platform receives normalized runtime-security events.
2. An anomaly detector scores at least one low-cardinality event-rate feature.
3. The detector result can be correlated with the underlying security events.

### Application and kernel telemetry correlation

Correlate application logs, traces, and metrics with kernel events. Vector normalizes and enriches the event stream; a later platform retains the enriched data and supports cross-event investigation.

**Success criteria**

1. Application telemetry and kernel events share workload identity through container or cgroup metadata.
2. Application logs include trace context and an application or agent run identifier.
3. A bounded correlation maps an application or agent run to kernel events from the same workload and time window.

### AI agent runtime monitoring

Correlate agent runtime telemetry with kernel events to detect unexpected data and network access by an AI agent.

**Success criteria**

1. Agent runtime telemetry identifies the agent, run, tool, and workload without collecting raw prompt or tool payloads by default.
2. Kernel events can be correlated to the agent workload and a bounded time window.
3. The system detects at least one unexpected outbound destination or file-access pattern.
