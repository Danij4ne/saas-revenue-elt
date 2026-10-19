# Cloud Run Job: batch app image (`python -m src run-all`). Recipe only —
# deploy.yml must not execute it (DECISIONS #15). Image tag is
# var.app_image_tag (CD writes github.sha). Cloud Run pins the digest at
# apply; a later push of the same mutable tag does not change the revision.
# Runs as elt-pipeline (`terraform/identity` SA; identities.tf data source), not github-deploy.
# dbt profiles.yml is baked into the app image (DBT_PROFILES_DIR=/app/dbt_profiles;
# DECISIONS #16). EnvSettings stay non-secret env from Terraform vars.
# RAW_SOURCE=gcs: Job fetches dumps from gs://<lake>/landing/ (DECISIONS #2).

locals {
  app_image = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${var.artifact_registry_repository_id}/saas-revenue-app:${var.app_image_tag}"
}

resource "google_cloud_run_v2_job" "app" {
  name                = var.cloud_run_job_name
  project             = var.gcp_project_id
  location            = var.gcp_region
  deletion_protection = false

  template {
    template {
      service_account = data.google_service_account.pipeline.email
      timeout         = "3600s"
      max_retries     = 0

      containers {
        image = local.app_image

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.gcp_project_id
        }
        env {
          name  = "GCP_LOCATION"
          value = var.gcp_location
        }
        env {
          name  = "GCS_BUCKET_NAME"
          value = var.bucket_name
        }
        env {
          name  = "BIGQUERY_RAW_DATASET"
          value = "raw"
        }
        env {
          name  = "ENVIRONMENT"
          value = var.environment
        }
        env {
          name  = "RAW_SOURCE"
          value = "gcs"
        }
      }
    }
  }

  depends_on = [google_project_service.run]
}
