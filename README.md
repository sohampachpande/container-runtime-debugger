# Container Runtime Visibility

An eBPF-assisted Linux debugging lab for Docker workloads. It correlates cgroup OOM kills with application logs and container resource metrics.

## First milestone: diagnose an OOM kill

The demo service intentionally allocates memory until Docker's cgroup memory limit kills it. The investigation connects three signals:

1. Docker reports the container's memory limit and exit status.
2. The application logs its allocation progress before it exits.
3. A later eBPF collector will observe the kernel OOM event and attribute it to the container cgroup.

## Run the demo

```sh
docker compose up --build
curl http://localhost:8080/healthz
curl 'http://localhost:8080/allocate?mb=1024'
docker compose ps
docker compose logs demo-app
```

The compose file limits the container to 64 MiB. The 1 GiB request reliably terminates it after the kernel enforces that limit. Inspect the result with:

```sh
docker inspect container-runtime-visibility-demo-app-1 \
  --format 'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}'
```

## Linux host requirement

The eBPF milestone needs a Linux kernel with BTF support, `bpftool`, and permission to load tracing programs. Docker Desktop on macOS is fine for the application demo, but run the eBPF collector in a Linux VM or Linux host so it can access the relevant kernel tracepoints and cgroups.

## Debugging workflow

For a cloud Linux host, see [the Terraform GCP lab setup](terraform/README.md).

Follow [the Docker OOM debugging workflow](docs/debugging-workflow.md) to reproduce the incident and diagnose it with application logs and Docker container state.

## Planned next milestone

Write an eBPF tracepoint program for OOM events, pass the PID and cgroup identity to a Go userspace process, and export a Prometheus counter labelled by container identity. The incident write-up should show the symptom, trace evidence, application logs, root cause, and remediation.
