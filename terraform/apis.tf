# CI (github-deploy) refreshes google_project_service via this API.
# Owner ADC often works without it; the SA does not. First enable on a
# virgin project is still manual (chicken-and-egg); this keeps it on.
resource "google_project_service" "cloudresourcemanager" {
  project            = var.gcp_project_id
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "bigquery" {
  project            = var.gcp_project_id
  service            = "bigquery.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "storage" {
  project            = var.gcp_project_id
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam" {
  project            = var.gcp_project_id
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

# WIF: GitHub Actions impersonates github-deploy (terraform/identity). Token exchange
# uses STS; generateAccessToken uses IAM Credentials. iam.googleapis.com above
# is the admin API for pools/providers, not the impersonation path.
resource "google_project_service" "iamcredentials" {
  project            = var.gcp_project_id
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "sts" {
  project            = var.gcp_project_id
  service            = "sts.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  project            = var.gcp_project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "run" {
  project            = var.gcp_project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudscheduler" {
  project            = var.gcp_project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "monitoring" {
  project            = var.gcp_project_id
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}
