output "environment" {
  description = "Deployment environment this configuration targeted (dev or prod)."
  value       = var.environment
}

output "data_lake_bucket_name" {
  description = "Name of the Google Cloud Storage bucket used as the data lake."
  value       = google_storage_bucket.data_lake.name
}

output "bigquery_dataset_ids" {
  description = "BigQuery datasets created for the ELT layers (including snapshots)."
  value       = { for id, ds in google_bigquery_dataset.datasets : id => ds.dataset_id }
}

output "pipeline_service_account_email" {
  description = "Email of the least-privilege SA for load + dbt. The Cloud Run Job runs as this SA. Account is managed in terraform/identity."
  value       = data.google_service_account.pipeline.email
}

output "github_deploy_service_account_email" {
  description = "Email of the CD SA (terraform apply via WIF). Account is managed in terraform/identity; GitHub var GCP_DEPLOY_SA."
  value       = data.google_service_account.github_deploy.email
}

output "artifact_registry_url" {
  description = "Docker hostname/path of the app repository (no image tag). deploy.yml job image pushes {url}/saas-revenue-app:{sha}."
  value       = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${var.artifact_registry_repository_id}"
}

output "cloud_run_job_name" {
  description = "Name of the Cloud Run Job (recipe only; deploy.yml does not execute it)."
  value       = google_cloud_run_v2_job.app.name
}

output "cloud_run_job_id" {
  description = "Full resource id of the Cloud Run Job (projects/…/locations/…/jobs/…)."
  value       = google_cloud_run_v2_job.app.id
}

output "scheduler_job_name" {
  description = "Name of the Cloud Scheduler job (paused by default; deploy.yml does not execute the Job)."
  value       = google_cloud_scheduler_job.app.name
}

output "scheduler_job_id" {
  description = "Full resource id of the Cloud Scheduler job (projects/…/locations/…/jobs/…)."
  value       = google_cloud_scheduler_job.app.id
}

output "scheduler_paused" {
  description = "Whether the cron is paused. Default true; unpause is a later tfvars change (DECISIONS #18)."
  value       = google_cloud_scheduler_job.app.paused
}

output "scheduler_service_account_email" {
  description = "Email of the Scheduler invoker SA. Cloud Scheduler oauth_token; run.invoker on the Job. Not elt-pipeline."
  value       = google_service_account.scheduler.email
}

output "alert_policy_name" {
  description = "Full resource name of the Job-failed alert policy. Deploy.yml does not execute the Job."
  value       = google_monitoring_alert_policy.job_failed.name
}

output "alert_notification_channel_name" {
  description = "Full resource name of the email notification channel. Verify the address in the GCP mail or notifications will not arrive."
  value       = google_monitoring_notification_channel.email.name
}
