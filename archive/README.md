# Archived GCP lab setup

Docker Desktop is the current development environment. Follow the
[local development guide](../docs/docker-desktop.md).

These files preserve the earlier GCP VM setup and verification instructions:

- [Terraform provisioning, access, dependencies, and lifecycle](terraform/README.md)
- [Native Linux Compose deployment](docs/compose.md)
- [GCP kernel and collector prerequisites](docs/gcp-host-preflight.md)

Run Terraform commands from `archive/terraform/`. Moving these files does not
stop, destroy, or change the existing cloud resources. Local state, variable
values, saved plans, and provider files remain ignored by Git.
