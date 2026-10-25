# GCP Linux lab

One Ubuntu 24.04 LTS VM for the Tetragon prerequisite checks. This configuration
creates infrastructure only; Docker, Tetragon, Vector, and the demo are separate steps.

## Choices and cost

- `e2-micro` in Oregon (`us-west1`) with a 30 GB `pd-standard` disk matches
  [Compute Engine free-tier resource limits](https://cloud.google.com/free/docs/free-cloud-features#compute).
  The allowance is shared across the billing account; existing usage can consume it.
- The VM has 1 GB RAM. Validate the collector first. Running Juice Shop, Vector,
  and Tetragon together may require a larger, billable VM.
- An ephemeral public IPv4 address enables package and container downloads.
  At $0.005/hour it costs about $3.65 per 730-hour month, separately from the free
  compute allowance. Network egress beyond the allowance is also billable.
  See [network pricing](https://cloud.google.com/vpc/network-pricing).
- SSH is permitted only through IAP's source range. Application ports are closed;
  use SSH port forwarding when the demo is deployed.
- No VM service account is attached. OS Login uses your Google identity rather
  than project-wide SSH keys. The connecting user needs OS Login administration
  and IAP tunnel access (or equivalent existing project permissions).
- The custom VPC has no NAT gateway or load balancer. Local Terraform state
  avoids adding a storage bucket for this single-operator lab.

## Authenticate and deploy

Run from this directory with `gcloud` and Terraform installed:

```sh
gcloud auth login
gcloud config set project container-runtime-visibility
gcloud auth application-default login
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -check
terraform validate
terraform plan -out=lab.tfplan
terraform apply lab.tfplan
```

Use an existing billing-enabled project. Enabling the Compute Engine and IAP
APIs requires service-usage permissions; Terraform manages their activation.
The APIs stay enabled when the lab is destroyed.

Terraform uses Application Default Credentials, which are separate from the CLI
login. Never commit credentials, local variable values, plan files, or state.
Commit `.terraform.lock.hcl` to preserve the selected provider version.

## Connect and verify

```sh
gcloud compute ssh runtime-visibility \
  --project=container-runtime-visibility \
  --zone=us-west1-b \
  --tunnel-through-iap
```

On the VM:

```sh
uname -m
uname -r
ls -lh /sys/kernel/btf/vmlinux
grep CONFIG_DEBUG_INFO_BTF "/boot/config-$(uname -r)"
stat -fc %T /sys/fs/cgroup
cat /sys/fs/cgroup/cgroup.controllers
free -h
```

The first gate is readable kernel BTF and cgroup v2. Successful Tetragon sensor
loading and a live execution event provide the functional collector check.
`bpftool` is a diagnostic aid, not an installation prerequisite.

Verified on the provisioned VM on 2026-10-25:

- IAP SSH and passwordless sudo work.
- Architecture: `x86_64`; running kernel: `7.0.0-1014-gcp`.
- `/sys/kernel/btf/vmlinux` is readable; `CONFIG_DEBUG_INFO_BTF=y` and
  `CONFIG_DEBUG_INFO_BTF_MODULES=y`.
- Cgroup v2 exposes the memory controller.
- About 953 MiB total RAM, with no swap configured.
- A subsequent Terraform plan reports no changes.

The initial checks established prerequisites. Tetragon's base sensor and live
host/container execution events were subsequently verified; see the software
inventory below and [Milestone 3 evidence](../docs/milestone.md).

## VM software inventory and installation

Observed on 2026-10-25. Terraform itself does not install this software.

| Software | Installation history and purpose |
|---|---|
| Docker Engine `29.1.3` | Already present before the collector session; runs the demo container |
| Git, Python 3, curl, tar, less | Already present; repository access, downloads, package extraction, and event inspection |
| Ubuntu kernel tools | Already present, but their `bpftool` wrapper cannot find a usable binary for this kernel |
| Tetragon and tetra `v1.7.0` | Installed during the collector session from the upstream amd64 release archive, after SHA-256 checksum verification |
| Bundled `bpftool v7.3.0` | Installed by that archive at `/usr/local/lib/tetragon/bpftool`; verified usable |
| Vector `0.60.0` | Runs as the root Compose `vector` service using `timberio/vector:0.60.0-alpine`; no host binary |
| Docker Compose `2.40.3` | Installed as Ubuntu package `docker-compose-v2` version `2.40.3+ds1-0ubuntu1~24.04.1`; runs the root stack |
| Tetragon BPF programs, support tools, and systemd unit | Installed by the same upstream installer under `/usr/local/` and `/usr/lib/systemd/system/` |
| Original OOM image | Built from the Python Dockerfile (now `test-app/Dockerfile`) as `runtime-visibility-demo-app:m3`, using `python:3.12-alpine`; retained for the separate OOM exercise |
| Current security demo image | Pulled upstream `bkimminich/juice-shop:v20.3.0`; selected by the default `compose.yaml` |

The initial collector and Vector sessions added no APT packages. The Compose
setup subsequently installed only `docker-compose-v2`, with no package
upgrades or removals. Buildx remains uninstalled; the original Python image
was built earlier with Docker's legacy builder.

The root Compose deployment now runs Tetragon, Vector, and Juice Shop as
separate containers. The native Tetragon service is inactive and disabled;
its previously installed binaries remain on disk. Tetragon writes raw JSON
to `/var/log/tetragon/tetragon.log`, and Vector reads that directory read-only.
The `vector-m4-data` external volume retains file-read checkpoints. Application
and metrics ports are bound to `127.0.0.1:3000` and `127.0.0.1:9598`.

Measured memory was about 65 MiB for Tetragon, 23 MiB for Vector, and 108 MiB
for Juice Shop, with about 275 MiB host memory available. This is a startup
observation, not a capacity guarantee. Keep development sources, configuration,
and docs in `~/container-runtime-visibility` on the same branch on both machines;
see [repository synchronization](../docs/compose.md#repository).

### Finalized deployment approach

The root `compose.yaml` declares Tetragon, Vector, and Juice Shop as separate
containers. Configuration remains under `collector/`; raw events stay in
`/var/log/tetragon/`, and the external `vector-m4-data` volume retains Vector
checkpoints. The [Compose guide](../docs/compose.md) documents prerequisites,
validation, lifecycle, logs, and fresh host/container acceptance checks.

The root Compose file, four Vector tests, and live host/container pipeline
were verified on the VM on 2026-10-25. Exactly one collector is active, the
three containers have no OOM kills or automatic restarts, and Juice Shop HTTP
readiness passed. Use `sudo python3 scripts/verify-pipeline.py` on the VM to
repeat the event correlation and counter-label checks.

During setup, `apt-get update` failed for the unrelated GitHub CLI repository
because signing key `5612B36462313325` was unavailable. The approved Compose
package installed from the existing signed Ubuntu indexes. That repository's
signing-key issue remains unresolved; no trust settings were weakened.

After the documented host setup, run on the Linux VM:

```sh
cd ~/container-runtime-visibility
sudo docker compose config --quiet
sudo docker compose up --detach
sudo docker compose ps
```

[`install-dep.sh`](install-dep.sh) remains as a record of the native Tetragon
bootstrap. It uses APT for missing `ca-certificates`, `curl`, `git`, `less`,
`python3`, and `tar`, and an upstream archive for Tetragon. It is not part of
the finalized Compose setup, does not install Compose, and has not been tested
on a fresh VM. No native Tetragon installation is needed for the container stack.

## Stop or remove the lab

Use the helper scripts from this directory:

```sh
./start.sh
./stop.sh
```

`start.sh` starts the VM and opens an IAP SSH session. `stop.sh` stops it.
Stopping preserves the disk but releases this VM's ephemeral external IP:

```sh
gcloud compute instances stop runtime-visibility \
  --project=container-runtime-visibility --zone=us-west1-b
```

To restart, use the same command with `start` instead of `stop`.
Retained disks continue counting toward storage usage.

## Remove the lab

To remove the lab, first review the deletion plan:

```sh
terraform plan -destroy
terraform destroy
```

Destroying the lab deletes its boot disk and all files on it. Preserve needed
files first. Keep the local state until Terraform finishes removing resources.
