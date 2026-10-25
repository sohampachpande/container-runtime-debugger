terraform {
  required_version = ">= 1.5, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = "us-west1"
  zone    = "us-west1-b"
}

variable "project_id" {
  description = "Existing GCP project with billing enabled."
  type        = string
}

resource "google_project_service" "compute" {
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iap" {
  service            = "iap.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_network" "lab" {
  name                    = "runtime-visibility"
  auto_create_subnetworks = false

  depends_on = [google_project_service.compute]
}

resource "google_compute_subnetwork" "lab" {
  name          = "runtime-visibility"
  ip_cidr_range = "10.20.0.0/24"
  network       = google_compute_network.lab.id
}

resource "google_compute_firewall" "ssh" {
  name          = "runtime-visibility-iap-ssh"
  network       = google_compute_network.lab.name
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["runtime-visibility"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance" "lab" {
  name         = "runtime-visibility"
  machine_type = "e2-micro"
  tags         = ["runtime-visibility"]

  boot_disk {
    auto_delete = true

    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = 30
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.lab.id

    # Outbound internet for apt and container pulls; IPv4 is billed separately.
    access_config {}
  }

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
  }

  # No service_account block: the lab does not need GCP API credentials.
  depends_on = [google_project_service.iap]
}

output "ssh_command" {
  description = "Connect through IAP using your existing gcloud identity."
  value       = "gcloud compute ssh ${google_compute_instance.lab.name} --project=${var.project_id} --zone=us-west1-b --tunnel-through-iap"
}
