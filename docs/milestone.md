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

## Milestone 3: Minimal eBPF OOM observer

Write a host-level eBPF program that listens for the relevant kernel OOM event and sends the killed process PID and cgroup identity to a userspace program.

**Success criteria**

1. The observer starts successfully on the Linux host.
2. Triggering the demo OOM produces one event with a PID and cgroup identifier.
3. The event is written to stdout in a readable format.

## Milestone 4: Container attribution and metric export

Resolve the observed cgroup to the Docker container, then export an OOM counter.

**Success criteria**

1. An OOM event identifies demo-app.
2. The counter includes container identity and cgroup identity.
3. The debugging workflow shows the Docker evidence and the corresponding eBPF event.
