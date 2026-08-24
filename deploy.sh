#!/usr/bin/env bash
# Deploy CurrentCut to Cloud Run.
#
# Run from Git Bash:  cd ~/dev/currentcut && bash deploy.sh
#
# --min-instances=1 and --no-cpu-throttling are not optional: an overnight run
# continues on a worker thread after the HTTP request that started it returns,
# and a throttled instance would freeze it mid-run.
#
# --max-instances is the outer bound on both the bill and the pipeline. The run
# budget in app/budget.py counts runs inside one process, so with no cap on
# processes it is a limit multiplied by however many instances Cloud Run decides
# to start - and the default is a hundred, each with two CPUs and no throttling.
# Four is far more than a demo needs (normal use never leaves the first) and
# turns "how much can this cost" into a number.
#
# Memory is the footage budget, not just the program's. Cloud Run's filesystem
# lives in memory, so every uploaded clip, every chunk being read and every
# rendered piece of the cut is counted against this number. 4Gi holds the
# public upload caps (config.UPLOAD_MAX_*) with room for the chunks in flight;
# raising those caps without raising this is how a long take becomes an
# out-of-memory kill. For real rush lengths, give the deployment an actual
# filesystem — a Cloud Storage volume mount — rather than buying enough memory
# to hold a night's footage.
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
  --memory=4Gi \
  --cpu=2 \
  --timeout=900 \
  --min-instances=1 \
  --max-instances=4 \
  --no-cpu-throttling \
  --set-secrets=GEMINI_API_KEY=currentcut-gemini-key:latest,PARALLEL_API_KEY=currentcut-parallel-key:latest

echo
echo "Deployed. Service URL:"
"$GCLOUD" run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --format="value(status.url)"
