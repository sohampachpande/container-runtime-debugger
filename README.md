# Container Runtime Visibility

An eBPF-assisted Linux runtime-security lab. Tetragon observes host and
container process activity, with OWASP Juice Shop as the security demo workload.

## First milestone: diagnose an OOM kill

The demo service intentionally allocates memory until Docker's cgroup memory limit kills it. The investigation connects three signals:

1. Docker reports the container's memory limit and exit status.
2. The application logs its allocation progress before it exits.
3. A later eBPF collector will observe the kernel OOM event and attribute it to the container cgroup.

## Run the Linux lab

The root Compose file declares separate Tetragon, Vector, and Juice Shop
containers. Follow [the Compose setup guide](docs/compose.md) first to prepare
the Linux host and persistent storage. The combined deployment and fresh
host/container event pipeline are verified on the VM.

```sh
sudo docker compose config --quiet
sudo docker compose pull
sudo docker compose up --detach
curl --fail http://localhost:3000/
curl --fail http://localhost:9598/metrics
sudo docker compose ps
sudo docker compose logs --follow vector
```

After startup, run `sudo python3 scripts/verify-pipeline.py` on the VM to repeat
the host/container event and counter checks.

Tetragon observes the Linux host and writes raw JSON to
`/var/log/tetragon/tetragon.log`. Vector reads it and emits normalized logs and
event counters. Juice Shop uses `bkimminich/juice-shop:v20.3.0` on loopback port
3000. The service limits are 256 MiB for Tetragon, 128 MiB for Vector, and
384 MiB for Juice Shop; measure actual resource use on the small VM.
For access from
your Mac, open an SSH tunnel:

```sh
gcloud compute ssh runtime-visibility \
  --project=container-runtime-visibility \
  --zone=us-west1-b \
  --tunnel-through-iap -- -L 3000:127.0.0.1:3000
```

Then browse to [Juice Shop](http://localhost:3000).

For ongoing development, run the full stack locally on Docker Desktop's Linux kernel using
[the Desktop override and commands](docs/docker-desktop.md). For the application
alone on macOS, use `docker compose up --detach juice-shop`. Stop the native Linux lab with
`sudo docker compose down`; event files and Vector's external checkpoint
volume are retained.

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
macOS runs its own Linux VM. The GCP Linux deployment and the local
[Docker Desktop deployment](docs/docker-desktop.md) are both verified; neither
collects events from the macOS kernel.

## Debugging workflow

For a cloud Linux host, see [the Terraform GCP lab setup](terraform/README.md).

Follow [the Docker OOM debugging workflow](docs/debugging-workflow.md) to reproduce the incident and diagnose it with application logs and Docker container state.

## Collector and pipeline status

Tetragon process execution and Docker container identity are verified on the
VM. See [the collector guide](docs/tetragon.md). Raw cgroup enrichment is
deferred, and additional event coverage follows incrementally.

Milestone 4's [Vector pipeline](docs/vector.md) reads Tetragon JSON, normalizes
process events, and exposes a low-cardinality event counter. File ingestion,
normalization, and counter labels are verified on the VM; a Prometheus rate
query remains unverified.

The root Compose definition is the lab entry point; all three containers and
the combined Linux pipeline have passed live validation.
