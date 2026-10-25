#!/usr/bin/env bash
set -euo pipefail

readonly project_id="container-runtime-visibility"
readonly zone="us-west1-b"
readonly instance="runtime-visibility"

gcloud compute instances stop "$instance" \
  --project="$project_id" \
  --zone="$zone"
