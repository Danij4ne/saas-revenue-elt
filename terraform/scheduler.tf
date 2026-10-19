# Cloud Scheduler: daily HTTP POST to Cloud Run Jobs :run (DECISIONS #18).
# Same module in dev and prod; paused by default (fail-closed). Does not
# execute on apply or on merge. deploy.yml must not call :run / execute.
# Invoker SA is not elt-pipeline: Cloud Scheduler's service agent gets
# actAs only on this SA (no lake/BQ). github-deploy needs actAs to create
# a scheduler job that uses oauth_token.

data "google_project" "current" {
  project_id = var.gcp_project_id
}

resource "google_service_account" "scheduler" {
  account_id   = var.scheduler_sa_account_id
  display_name = "ELT scheduler (Cloud Run Job invoker)"
  description  = "Least-privilege identity for Cloud Scheduler to start the Cloud Run Job. Not used for load, dbt, or terraform apply."
  project      = var.gcp_project_id

  depends_on = [google_project_service.iam]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_job.app.name
  role     = "roles/run.invoker"
  member   = google_service_account.scheduler.member
}

# Tick-time token minting. Do not grant this on elt-pipeline.
resource "google_service_account_iam_member" "scheduler_service_agent_act_as" {
  service_account_id = google_service_account.scheduler.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

  depends_on = [google_project_service.cloudscheduler]
}

# Creating a scheduler job with oauth_token requires actAs on that SA.
resource "google_service_account_iam_member" "github_deploy_act_as_scheduler" {
  service_account_id = google_service_account.scheduler.name
  role               = "roles/iam.serviceAccountUser"
  member             = data.google_service_account.github_deploy.member
}

resource "google_cloud_scheduler_job" "app" {
  name             = var.scheduler_job_name
  description      = "Daily trigger for the Cloud Run Job. Paused until an explicit unpause; does not run the ELT on apply."
  project          = var.gcp_project_id
  region           = var.gcp_region
  schedule         = var.scheduler_schedule
  time_zone        = var.scheduler_time_zone
  paused           = var.scheduler_paused
  attempt_deadline = "180s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.gcp_region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.gcp_project_id}/jobs/${google_cloud_run_v2_job.app.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_job_iam_member.scheduler_invoker,
    google_service_account_iam_member.scheduler_service_agent_act_as,
    google_service_account_iam_member.github_deploy_act_as_scheduler,
  ]
}
