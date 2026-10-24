# Milestones

## Milestone 1: Docker OOM debugging demo — complete

The demo Python service runs in a container with a 64 MiB memory limit. A 1 GiB allocation request causes the Linux kernel to kill the process.

**Verified evidence**

- Application logs show allocation progress until termination.
- Docker reports OOMKilled=true and exit code 137.
- Docker reports an applied memory limit of 64 MiB.

See [the debugging workflow](debugging-workflow.md).

## Milestone 2: Linux host setup — complete

The project was cloned to a Raspberry Pi 5, then Docker Compose reproduced and diagnosed the memory-constrained OOM kill. See [the Raspberry Pi setup](linux-host-setup.md).

**Verified**

1. Docker Compose starts the demo service.
2. The health endpoint responds successfully.
3. The 1 GiB allocation request reproduces the OOM kill.
4. The cgroup v2 memory controller is enabled with cgroup_enable=memory.

**Still required before eBPF work**

1. The host exposes BTF metadata at /sys/kernel/btf/vmlinux.
2. sudo bpftool feature probe kernel reports the available BPF capabilities.

## Milestone 3: eBPF event pipeline and process execution

Build the host-level security telemetry agent described in [the eBPF collector design](ebpf-collector.md). Its first event source is process execution.

**Success criteria**

1. The agent starts successfully on the Linux host.
2. A process execution produces one structured event with host PID, process name, and cgroup identity.
3. The event is written as JSON to stdout.

## Milestone 4: Vector event pipeline

Route custom-agent events through Vector and derive low-cardinality event-rate metrics.

**Success criteria**

1. Vector receives structured events from the custom agent.
2. Vector outputs normalized events and an event-rate metric.
3. Metric labels exclude high-cardinality fields such as PID and raw file paths.

## Milestone 5: Collector event coverage and container attribution

Make the pipeline able to process every event schema emitted by the collector without adding event-specific pipeline logic. Expand collector coverage incrementally, beginning with OOM victims and then file-access patterns.

**Success criteria**

1. Process execution events identify demo-app.
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
