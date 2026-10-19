# IAM/WIF state (DECISIONS #17). Same GCS tfstate *bucket* as the app root,
# different prefix so deploy.yml never applies this module.
# Copy backend-dev.hcl.example → backend-dev.hcl (gitignored) and:
#   terraform init -backend-config=backend-dev.hcl
# Prod: backend-prod.hcl. Never -migrate-state without an explicit OK.

terraform {
  backend "gcs" {}
}
