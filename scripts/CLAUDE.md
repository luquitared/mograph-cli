# scripts/

Operational scripts for deployment and asset management.

## Files

- `deploy.sh` — Deploys to Cloud Run via `gcloud builds submit --config cloudrun/cloudbuild.yaml`. Writes a `VERSION` file with git commit, branch, and deploy timestamp before submitting. Supports `--env staging` for staging environment deployment.
## Dependencies

- **Imported by**: nothing (standalone scripts)
- `deploy.sh` depends on `cloudrun/cloudbuild.yaml` and `gcloud` CLI
