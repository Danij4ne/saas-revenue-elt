# Alert when the Cloud Run Job finishes failed (DECISIONS #19).
# Email channel only — address is var.alert_email (tfvars / CD, not git).
# Does not execute the Job. Pipeline stdout already lands in Cloud Logging.

resource "google_monitoring_notification_channel" "email" {
  project      = var.gcp_project_id
  display_name = "ELT job failed (${var.environment})"
  type         = "email"
  description  = "Doorbell for Cloud Run Job failures. Verify the address in the GCP email or mail will not arrive."
  enabled      = true

  labels = {
    email_address = var.alert_email
  }

  user_labels = {
    env = var.environment
  }

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_alert_policy" "job_failed" {
  project      = var.gcp_project_id
  display_name = "Cloud Run Job failed (${var.cloud_run_job_name})"
  combiner     = "OR"
  enabled      = true
  severity     = "ERROR"

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    mime_type = "text/markdown"
    content   = "The Cloud Run Job finished failed. Open Cloud Logging for that Job. Do not unpause the Scheduler or click Ejecutar without an explicit OK. The Job reads gs://<lake>/landing/ (RAW_SOURCE=gcs); seed that prefix first."
    subject   = "ELT Cloud Run Job failed (${var.environment})"
  }

  user_labels = {
    env = var.environment
  }

  conditions {
    display_name = "Completed execution result = failed"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_job\" AND resource.labels.job_name = \"${google_cloud_run_v2_job.app.name}\" AND resource.labels.location = \"${var.gcp_region}\" AND metric.type = \"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result = \"failed\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_DELTA"
      }

      evaluation_missing_data = "EVALUATION_MISSING_DATA_INACTIVE"
    }
  }

  depends_on = [google_project_service.monitoring]
}
