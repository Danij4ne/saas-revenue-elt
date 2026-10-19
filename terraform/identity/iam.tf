# Pipeline identity. Created here so project-level jobUser is not in the
# CD-applied app root (DECISIONS #17). Lake objectAdmin and dataset dataEditor
# stay in terraform/iam.tf (bucket/dataset IAM, not project setIamPolicy).

resource "google_service_account" "pipeline" {
  account_id   = var.pipeline_sa_account_id
  display_name = "ELT pipeline (load + dbt)"
  description  = "Least-privilege identity for GCS raw load and BigQuery/dbt. Not used for Terraform state."
  project      = var.gcp_project_id
}

resource "google_project_iam_member" "pipeline_bq_job_user" {
  project = var.gcp_project_id
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.pipeline.member
}
