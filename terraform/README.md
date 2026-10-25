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

The first gate is readable kernel BTF and cgroup v2. Docker and a BPF capability
probe are still needed before marking the host preflight complete.

Verified on the provisioned VM on 2026-10-25:

- IAP SSH and passwordless sudo work.
- Architecture: `x86_64`; running kernel: `7.0.0-1014-gcp`.
- `/sys/kernel/btf/vmlinux` is readable; `CONFIG_DEBUG_INFO_BTF=y` and
  `CONFIG_DEBUG_INFO_BTF_MODULES=y`.
- Cgroup v2 exposes the memory controller.
- About 953 MiB total RAM, with no swap configured.
- A subsequent Terraform plan reports no changes.

This verifies the host's BTF prerequisite, not Tetragon compatibility. The BPF
probe and collector startup remain to be tested on this kernel.

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
