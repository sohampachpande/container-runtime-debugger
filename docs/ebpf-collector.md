# eBPF Security Telemetry Collection

## Goal

Use Tetragon as the host-level eBPF collector for kernel events relevant to runtime security and container health. OOM kills are one event type, not the product boundary.

The project focuses on learning eBPF event semantics, runtime visibility, and security analysis. Tetragon's structured JSON and gRPC events retain process and workload context while its tracing policies expose focused kernel hooks. The project builds the normalization, pipeline, attribution, and detection layers around those events. It is observability-only in its first versions; kernel-level enforcement is a later, separate decision.

## Architecture

The collection path has three layers:

1. Tetragon attaches eBPF programs and emits process, syscall, file, network, and other supported runtime events.
2. Vector receives collector output, normalizes event fields, and routes structured events and low-cardinality metrics.
3. A workload-analysis layer resolves or validates cgroup identity against Docker containers now and Kubernetes workloads later.

The normalized event envelope will carry a timestamp, event type, host PID and TGID, process name, UID, and cgroup identity. Event-specific fields are added only when they are available from the selected collector and hook.

## First event source: process execution

Start with the collector's process-execution events. Unlike an OOM victim, the process is alive when this event is emitted, so its cgroup identity can be validated directly and used to establish reliable container attribution.

Milestone 3 first verifies a raw JSON execution event from a live host process
and checks its host PID, process name, and available cgroup identity. Vector
normalization and demo-container attribution follow in later milestones.

Use [the Tetragon guide](tetragon.md) for the initial GCP deployment
and live-process verification.

## Subsequent event sources

Add each source through the same event pipeline:

1. OOM victim events, subject to the selected collector and Pi exposing the required event.
2. File-access events selected from the collector's supported policies and hooks.
3. Network and additional security events selected after OOM and file-access patterns are validated.

The capability probe and collector startup output determine which optional event sources are available. The pipeline should report unsupported modules rather than assume every Linux host has identical BPF features.

## Deployment model

Do not place this agent in an application image base layer. A host collector needs host kernel access; embedding it in every workload would create duplicate privileged observers and incomplete node coverage.

For Docker, package it as a dedicated agent image that runs once per host with the host paths and capabilities required by the selected BPF programs.

For Kubernetes, package the same agent image as a DaemonSet so one instance runs on each eligible node. Begin with a privileged development deployment, then replace it with the smallest verified capability and host-mount set after the required probes are known.

## GCP collector-host preflight

~~~sh
uname -m
uname -r
test -r /sys/kernel/btf/vmlinux && echo "BTF available"
grep -E 'CONFIG_DEBUG_INFO_BTF(=y|_MODULES=y)' "/boot/config-$(uname -r)"
stat -fc %T /sys/fs/cgroup
cat /sys/fs/cgroup/cgroup.controllers
sudo cat /sys/kernel/tracing/events/sched/sched_process_exec/format
sudo test -r /sys/kernel/tracing/events/oom/mark_victim/format
~~~

`bpftool` is a diagnostic aid, not a Tetragon prerequisite. Run the capability
probe when the command is usable:

~~~sh
if sudo bpftool version; then
  sudo bpftool feature probe kernel
else
  echo "bpftool is unavailable for this kernel; continue to Tetragon startup"
fi
~~~

The BTF checks establish a prerequisite for loading Tetragon's CO-RE programs;
successful collector startup and event capture remain the functional check.
The cgroup checks confirm the memory controller needed for workload and
OOM attribution. The tracepoint format files define the fields available from
this kernel. `bpftool` reports the available BPF program, map, and helper
features when a matching binary is available. On the current Ubuntu 24.04 GCP
image, the `linux-tools-$(uname -r)` package is installed but does not ship
`bpftool`, and the Ubuntu archive has no standalone `bpftool` package. Record
that result and continue to Tetragon startup; its successful load is the
collector's functional kernel check.

After the native Tetragon installation, its package supplies a usable
`/usr/local/lib/tetragon/bpftool` (`v7.3.0` verified on 2026-10-25). Use that
explicit path rather than the Ubuntu wrapper. The base sensor and a live
execution event are now verified; see [Milestone 3 evidence](milestone.md#milestone-3-ebpf-event-pipeline-and-process-execution)
for the remaining cgroup-identity gap.

The current Raspberry Pi kernel lacks BTF, so use the GCP Ubuntu test VM for
this preflight. See [the Terraform lab setup](../terraform/README.md) for the
IAP SSH command.
