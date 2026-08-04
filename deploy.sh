#!/usr/bin/env bash
# Deploy CurrentCut to Cloud Run.
#
# Run from Git Bash:  cd ~/dev/currentcut && bash deploy.sh
#
# --min-instances=1 and --no-cpu-throttling are not optional: an overnight run
# continues on a worker thread after the HTTP request that started it returns,
# and a throttled instance would freeze it mid-run.
set -euo pipefail

PROJECT=clearslate-demo-2026
REGION=asia-northeast1
SERVICE=currentcut
GCLOUD="${GCLOUD_BIN:-/c/Users/PC_USER/google-cloud-sdk/bin/gcloud.cmd}"

cd "$(dirname "$0")"

echo "Deploying $SERVICE to $PROJECT / $REGION"
echo "Account: $("$GCLOUD" config get-value account 2>/dev/null)"
echo

"$GCLOUD" run deploy "$SERVICE" \
  --project="$PROJECT" \
  --source . \
  --region="$REGION" \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=900 \
  --min-instances=1 \
  --no-cpu-throttling \
  --set-secrets=GEMINI_API_KEY=currentcut-gemini-key:latest,PARALLEL_API_KEY=currentcut-parallel-key:latest

echo
echo "Deployed. Service URL:"
"$GCLOUD" run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --format="value(status.url)"
