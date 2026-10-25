# Container Runtime Visibility

An eBPF-assisted Linux runtime-security lab. Tetragon observes host and
container process activity, with OWASP Juice Shop as the security demo workload.

## First milestone: diagnose an OOM kill

The demo service intentionally allocates memory until Docker's cgroup memory limit kills it. The investigation connects three signals:

1. Docker reports the container's memory limit and exit status.
2. The application logs its allocation progress before it exits.
3. A later eBPF collector will observe the kernel OOM event and attribute it to the container cgroup.

## Run the demo

```sh
docker compose up --detach
curl --fail http://localhost:3000/
docker compose ps
docker compose logs juice-shop
```

The default workload uses the upstream `bkimminich/juice-shop:v20.3.0` image,
binds port 3000 to loopback, and has a 384 MiB memory limit. Measure startup and
runtime memory before adding more services to the small VM. For access from
your Mac, open an SSH tunnel:

```sh
gcloud compute ssh runtime-visibility \
  --project=container-runtime-visibility \
  --zone=us-west1-b \
  --tunnel-through-iap -- -L 3000:127.0.0.1:3000
```

Then browse to [Juice Shop](http://localhost:3000).

## Original OOM exercise

The Python workload in `test-app/` remains available separately through
`compose.oom.yaml`:

```sh
docker compose -f compose.oom.yaml up --build --detach
curl http://localhost:8080/healthz
curl 'http://localhost:8080/allocate?mb=1024'
```

Its 64 MiB limit and diagnostic steps are documented in
[the Docker OOM workflow](docs/debugging-workflow.md). Stop Juice Shop before
running the OOM exercise on the small VM.

## Linux host requirement

The eBPF milestone needs a Linux kernel with BTF support and permission to load
tracing programs. `bpftool` is an optional diagnostic aid. Docker Desktop on
macOS is fine for the application demo; use the GCP Linux VM for Tetragon.

## Debugging workflow

For a cloud Linux host, see [the Terraform GCP lab setup](terraform/README.md).

Follow [the Docker OOM debugging workflow](docs/debugging-workflow.md) to reproduce the incident and diagnose it with application logs and Docker container state.

## Planned next milestone

Install Tetragon and validate a process-execution JSON event against a live host
process. Follow [the collector setup](docs/tetragon.md). Vector routing,
container attribution, and additional event sources follow after this check.
