# CD identity. GitHub Actions (OIDC) impersonates this SA to terraform
# apply the *app* root. Not elt-pipeline. No google_service_account_key.
# This module is local ADC only — deploy.yml never inits this backend
# (DECISIONS #17). Import existing SAs/WIF/IAM before the first apply;
# do not recreate them.
#
# github-deploy project roles are what CD needs to apply terraform/ (AR,
# Run, Scheduler, Monitoring, serviceUsage, serviceAccountAdmin). No
# projectIamAdmin (cannot escalate to owner). No storage.admin /
# bigquery.admin at project scope (no all-buckets / all-tables data).
# Lake storage.admin and dataset dataOwner for CD are in the app root
# (bucket/dataset IAM). roles/storage.bucketAdmin is not a GCS role.
# Leftover project bindings from the old single-root module must be
# removed with gcloud after import+apply (Terraform cannot destroy
# bindings it never imported). See DECISIONS #17.

locals {
  github_wif_pool_id     = "github-actions"
  github_wif_provider_id = "github"

  github_deploy_project_roles = toset([
    "roles/iam.serviceAccountAdmin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/artifactregistry.admin",
    "roles/artifactregistry.writer",
    "roles/run.admin",
    "roles/cloudscheduler.admin",
    "roles/monitoring.alertPolicyEditor",
    "roles/monitoring.notificationChannelEditor",
  ])
}

resource "google_service_account" "github_deploy" {
  account_id   = var.github_deploy_sa_account_id
  display_name = "GitHub Actions CD (terraform apply)"
  description  = "WIF-only identity for deploy.yml. Not used for load, dbt, or Cloud Run."
  project      = var.gcp_project_id
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.gcp_project_id
  workload_identity_pool_id = local.github_wif_pool_id
  display_name              = "GitHub Actions"
  description               = "OIDC identities from GitHub Actions."
  disabled                  = false
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.gcp_project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = local.github_wif_provider_id
  display_name                       = "GitHub OIDC"
  description                        = "token.actions.githubusercontent.com — this repo, main only."
  disabled                           = false

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  attribute_condition = <<-EOT
    attribute.repository == "${var.github_repository}" &&
    assertion.ref == "refs/heads/main" &&
    assertion.ref_type == "branch"
  EOT

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_deploy_wif" {
  service_account_id = google_service_account.github_deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_project_iam_member" "github_deploy" {
  for_each = local.github_deploy_project_roles

  project = var.gcp_project_id
  role    = each.value
  member  = google_service_account.github_deploy.member
}

# Per-environment tfstate bucket (not a resource in this module). Dev and
# prod never share a bucket — prefix isolation is extra namespacing, not the
# prod/dev boundary.
resource "google_storage_bucket_iam_member" "github_deploy_tfstate" {
  bucket = var.tfstate_bucket_name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.github_deploy.member
}

resource "google_service_account_iam_member" "github_deploy_act_as_pipeline" {
  service_account_id = google_service_account.pipeline.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.github_deploy.member
}
