# eBPF Security Telemetry Agent

## Goal

Build a host-level agent that observes kernel events relevant to runtime security and container health. OOM kills are one event type, not the product boundary.

The agent is observability-only in its first versions. It reports what occurred; kernel-level enforcement is a later, separate decision.

## Architecture

The agent has three layers:

1. CO-RE eBPF programs in C attach to kernel tracepoints and write compact events to a ring buffer.
2. A Go userspace process loads the programs, reads ring-buffer events, and writes structured JSON to stdout.
3. A host-enrichment layer resolves cgroup identity to Docker containers now and Kubernetes workloads later.

The event envelope will carry a timestamp, event type, host PID and TGID, process name, UID, and cgroup identity. Event-specific fields are added only when they are available at the chosen kernel hook.

## First event source: process execution

Start with the sched/sched_process_exec tracepoint. Unlike an OOM victim, the process is alive when this event is emitted, so the agent can capture its cgroup identity directly and establish reliable container attribution.

The first success case is a JSON execution event from the demo container containing its host PID, process name, and cgroup identity.

## Subsequent event sources

Add each source through the same event pipeline:

1. OOM victim events from oom/mark_victim, subject to the Pi exposing that tracepoint.
2. File-access events selected from the host's supported tracepoints or LSM hooks.
3. Additional security events selected after OOM and file-access patterns are validated.

The capability probe determines which optional hooks can be enabled. The agent should report unsupported modules at startup rather than assume every Linux host has identical BPF features.

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
