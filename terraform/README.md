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
| Tetragon BPF programs, support tools, and systemd unit | Installed by the same upstream installer under `/usr/local/` and `/usr/lib/systemd/system/` |
| Original OOM image | Built from the Python Dockerfile (now `test-app/Dockerfile`) as `runtime-visibility-demo-app:m3`, using `python:3.12-alpine`; retained for the separate OOM exercise |
| Current security demo image | Pulled upstream `bkimminich/juice-shop:v20.3.0`; selected by the default `compose.yaml` |

No APT packages were installed during this collector session. Docker Compose,
Buildx, and Vector were not installed. Docker's existing legacy builder was
sufficient for this demo image; no Tetragon source compilation was needed.

The demo is running as `juice-shop-m3` with a 384 MiB memory limit and
`127.0.0.1:3000` published on the VM. The previous `demo-app-m3` container is
stopped, and its 64 MiB OOM exercise is retained in `compose.oom.yaml`.
Juice Shop passed HTTP readiness and used about 136 MiB after startup;
available host memory was about 245 MiB at that check. Tetragon is enabled on boot. Its active
configuration is in `/etc/tetragon/tetragon.conf.d/`, and runtime event files
are under `/var/log/tetragon/`. Keep development sources, configuration, and
docs in `~/container-runtime-visibility` on the active branch on both machines.
The Git and working-tree synchronization workflow is documented in
[the Tetragon guide](../docs/tetragon.md#2-keep-development-files-in-the-repository).

### Reproduce the collector installation

APT does not use a universal `requirements.txt` convention. The repository's
[`install-dep.sh`](install-dep.sh) lists its APT prerequisites explicitly:
`ca-certificates`, `curl`, `git`, `less`, `python3`, and `tar`. It installs only
missing packages, then downloads and verifies the pinned Tetragon release for
a fresh installation. It does not install Docker, Compose, Buildx, or Vector.

After synchronizing the repository, run **on the Ubuntu x86_64 VM**:

```sh
cd ~/container-runtime-visibility
bash terraform/install-dep.sh
```

The script checks BTF and cgroup v2, requires sudo, and uses the repository's
collector configuration. A fresh install enables and starts Tetragon. If
Tetragon or tetra already exists, it leaves that deployment unchanged rather
than reinstalling or upgrading it. Review the upstream installer as described
in [the manual runbook](../docs/tetragon.md#3-install-and-check-startup) if desired.

The script is not a Terraform provisioner and was added after the manual
installation; the fresh-install path has not been executed on a clean VM.
Installation alone does not complete Milestone 3: follow the guide to check
sensor loading, resource use, and actual execution-event metadata.

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
