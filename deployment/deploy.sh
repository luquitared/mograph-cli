#!/bin/bash
# Deploy explainer-mograph to Google Cloud Run
# Rebuilds the Docker image and pushes to Cloud Run

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Parse arguments
ENV="prod"
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --env) ENV="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

if [ "$ENV" != "prod" ] && [ "$ENV" != "staging" ]; then
    echo "Error: --env must be 'prod' or 'staging' (got '$ENV')"
    exit 1
fi

echo "Deploying explainer-mograph ($ENV) to Cloud Run..."
echo "Project directory: $PROJECT_DIR"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI is not installed"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 | grep -q .; then
    echo "Error: Not authenticated with gcloud. Run 'gcloud auth login'"
    exit 1
fi

# Get current project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No GCP project set. Run 'gcloud config set project PROJECT_ID'"
    exit 1
fi

echo "Using GCP project: $PROJECT_ID"
echo ""

# Write version info for tracking deployed commits
GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=$(git diff --quiet 2>/dev/null && echo "" || echo "-dirty")
DEPLOY_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cat > "$PROJECT_DIR/VERSION" <<VEOF
{
  "commit": "${GIT_COMMIT}${GIT_DIRTY}",
  "branch": "$GIT_BRANCH",
  "deployed_at": "$DEPLOY_TIME"
}
VEOF

echo "Version info: commit=${GIT_COMMIT}${GIT_DIRTY} branch=${GIT_BRANCH}"

# Build substitutions for staging environment
SUBSTITUTIONS=""
if [ "$ENV" = "staging" ]; then
    SUBSTITUTIONS="_SERVICE_NAME=explainer-mograph-staging,_MAX_INSTANCES=3"
fi

# Submit build to Cloud Build
if [ -n "$SUBSTITUTIONS" ]; then
    echo "Using substitutions: $SUBSTITUTIONS"
    gcloud builds submit --config cloudrun/cloudbuild.yaml --substitutions="$SUBSTITUTIONS" .
else
    gcloud builds submit --config cloudrun/cloudbuild.yaml .
fi

echo ""
echo "Deployment complete! (env: $ENV)"
if [ "$ENV" = "staging" ]; then
    echo "Service URL: https://explainer-mograph-staging-$(gcloud config get-value project | tr ':' '-')-uc.a.run.app"
else
    echo "Service URL: https://explainer-mograph-$(gcloud config get-value project | tr ':' '-')-uc.a.run.app"
fi
