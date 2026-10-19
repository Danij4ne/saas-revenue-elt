# Pipeline and CD service accounts live in terraform/identity (DECISIONS #17).
# This root only reads them so lake/Job IAM can bind without projectIamAdmin.

data "google_service_account" "pipeline" {
  account_id = var.pipeline_sa_account_id
  project    = var.gcp_project_id
}

data "google_service_account" "github_deploy" {
  account_id = var.github_deploy_sa_account_id
  project    = var.gcp_project_id
}
