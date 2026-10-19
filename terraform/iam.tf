# Pipeline lake/dataset IAM. The pipeline SA itself and project jobUser
# live in terraform/identity (DECISIONS #17). Local load/dbt keep using ADC.
# Cloud Run runs as this SA.
# IAM uses *_iam_member (additive), not *_iam_policy.
# github-deploy: lake-scoped storage.admin (not project storage.admin) and
# dataset dataOwner (not project bigquery.admin). roles/storage.bucketAdmin
# is not a grantable GCS role (GCP 400 on project and on bucket).

resource "google_storage_bucket_iam_member" "pipeline_lake_object_admin" {
  bucket = google_storage_bucket.data_lake.name
  role   = "roles/storage.objectAdmin"
  member = data.google_service_account.pipeline.member
}

resource "google_storage_bucket_iam_member" "github_deploy_lake_storage_admin" {
  bucket = google_storage_bucket.data_lake.name
  role   = "roles/storage.admin"
  member = data.google_service_account.github_deploy.member
}

resource "google_bigquery_dataset_iam_member" "pipeline_data_editor" {
  for_each   = google_bigquery_dataset.datasets
  project    = var.gcp_project_id
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = data.google_service_account.pipeline.member
}

resource "google_bigquery_dataset_iam_member" "github_deploy_data_owner" {
  for_each   = google_bigquery_dataset.datasets
  project    = var.gcp_project_id
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataOwner"
  member     = data.google_service_account.github_deploy.member
}
