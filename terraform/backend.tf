# Remote state on GCS. Backend blocks do not accept variables, so bucket
# and prefix live in backend-*.hcl, not here.
# Copy the matching .example to the gitignored file and run:
#   terraform init -backend-config=backend-prod.hcl
# The state bucket is separate from the data lake and must already exist.
# Switch environments with -reconfigure; do not run -migrate-state again
# without an explicit OK.

terraform {
  backend "gcs" {}
}
