# Private Docker repo for the app image (load + dbt). Not Airflow.
# Terraform creates the empty repository; deploy.yml job `image` builds and
# pushes (tag = github.sha). elt-pipeline pulls this image.
# On env=dev, github-deploy@prod may read this repo so image-prod copies
# the digest instead of rebuilding (DECISIONS #15).

resource "google_artifact_registry_repository" "app" {
  project       = var.gcp_project_id
  location      = var.gcp_region
  repository_id = var.artifact_registry_repository_id
  description   = "App image (load + dbt). Not Airflow."
  format        = "DOCKER"

  # CD tags every image with github.sha. KEEP TAGGED would match all
  # versions and delete nothing (DECISIONS #15). dry_run: GCP records
  # the policy but does not delete until an explicit flip.
  cleanup_policy_dry_run = true

  cleanup_policies {
    id     = "keep-minimum-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count            = 10
      package_name_prefixes = ["saas-revenue-app"]
    }
  }

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "2592000s"
    }
  }

  depends_on = [google_project_service.artifactregistry]

  lifecycle {
    precondition {
      condition = (
        var.environment == "dev" && can(regex("^serviceAccount:[^@]+@.+$", var.ar_promote_reader_member))
        ) || (
        var.environment == "prod" && var.ar_promote_reader_member == ""
      )
      error_message = "dev requires ar_promote_reader_member (serviceAccount:email of prod github-deploy); prod must leave it empty."
    }
  }
}

resource "google_artifact_registry_repository_iam_member" "pipeline_reader" {
  project    = google_artifact_registry_repository.app.project
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = data.google_service_account.pipeline.member
}

resource "google_artifact_registry_repository_iam_member" "promote_reader" {
  count = var.ar_promote_reader_member == "" ? 0 : 1

  project    = google_artifact_registry_repository.app.project
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = var.ar_promote_reader_member
}
