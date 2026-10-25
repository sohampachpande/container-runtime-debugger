#!/usr/bin/env bash
set -euo pipefail

readonly project_id="container-runtime-visibility"
readonly zone="us-west1-b"
readonly instance="runtime-visibility"

gcloud compute instances start "$instance" \
  --project="$project_id" \
  --zone="$zone"

gcloud compute ssh "$instance" \
  --project="$project_id" \
  --zone="$zone" \
  --tunnel-through-iap
