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

The first success case is a normalized JSON execution event from the demo container containing its host PID, process name, and cgroup identity.

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

## Raspberry Pi preflight

~~~sh
test -r /sys/kernel/btf/vmlinux && echo "BTF available"
sudo bpftool feature probe kernel
sudo cat /sys/kernel/tracing/events/sched/sched_process_exec/format
sudo test -r /sys/kernel/tracing/events/oom/mark_victim/format
~~~

The first command confirms CO-RE metadata is present. The capability probe identifies supported BPF program and map types. The tracepoint format files define the fields available to the agent on this kernel.
