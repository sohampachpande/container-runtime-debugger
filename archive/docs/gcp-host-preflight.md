# GCP collector-host preflight

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
execution event are now verified; see [Milestone 3 evidence](../../docs/milestone.md#milestone-3-ebpf-event-pipeline-and-process-execution)
for the remaining cgroup-identity gap.

The current Raspberry Pi kernel lacks BTF, so use the GCP Ubuntu test VM for
this preflight. See [the Terraform lab setup](../terraform/README.md) for the
IAP SSH command.
