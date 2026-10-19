locals {
  # Dataset default is milliseconds; the policy is expressed in days (DECISIONS #14).
  raw_partition_expiration_ms = var.raw_partition_expiration_days * 24 * 60 * 60 * 1000

  # One map is the source of truth for dataset resources and IAM (DECISIONS #14).
  # Only raw has a partition-expiration window; snapshots is the SCD2 container
  # (tables stay dbt-owned).
  bq_datasets = {
    raw = {
      layer                           = "raw"
      default_partition_expiration_ms = local.raw_partition_expiration_ms
    }
    staging = {
      layer                           = "staging"
      default_partition_expiration_ms = null
    }
    intermediate = {
      layer                           = "intermediate"
      default_partition_expiration_ms = null
    }
    marts = {
      layer                           = "marts"
      default_partition_expiration_ms = null
    }
    snapshots = {
      layer                           = "snapshots"
      default_partition_expiration_ms = null
    }
  }
}

resource "google_storage_bucket" "data_lake" {
  name          = var.bucket_name
  location      = var.gcp_location
  storage_class = var.bucket_storage_class

  uniform_bucket_level_access = true
  # DECISIONS #14: UBLA is not enough — enforced makes allUsers impossible.
  public_access_prevention = "enforced"

  versioning {
    enabled = true
  }

  # Object lifecycle. Distinct from lifecycle.prevent_destroy below.
  # Live objects under the raw prefix cool in place; they are never deleted.
  # Noncurrent generations of the same object name expire after a short window.
  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age                   = var.lake_lifecycle_nearline_age_days
      matches_prefix        = [var.lake_lifecycle_object_prefix]
      matches_storage_class = ["STANDARD"]
      with_state            = "LIVE"
    }
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
    condition {
      age                   = var.lake_lifecycle_coldline_age_days
      matches_prefix        = [var.lake_lifecycle_object_prefix]
      matches_storage_class = ["NEARLINE"]
      with_state            = "LIVE"
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      days_since_noncurrent_time = var.lake_lifecycle_noncurrent_days
      matches_prefix             = [var.lake_lifecycle_object_prefix]
      with_state                 = "ARCHIVED"
      send_age_if_zero           = false
    }
  }

  lifecycle_rule {
    action {
      type = "AbortIncompleteMultipartUpload"
    }
    condition {
      age = var.lake_lifecycle_abort_incomplete_days
    }
  }

  labels = {
    project = "saas-revenue-elt"
    env     = var.environment
    layer   = "data-lake"
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = var.lake_lifecycle_coldline_age_days > var.lake_lifecycle_nearline_age_days
      error_message = "lake_lifecycle_coldline_age_days must be greater than lake_lifecycle_nearline_age_days (age is days since object creation)."
    }
  }

  depends_on = [
    google_project_service.storage,
  ]
}

resource "google_bigquery_dataset" "datasets" {
  for_each = local.bq_datasets

  dataset_id                      = each.key
  location                        = var.gcp_location
  default_partition_expiration_ms = each.value.default_partition_expiration_ms

  labels = {
    project = "saas-revenue-elt"
    env     = var.environment
    layer   = each.value.layer
  }

  # Same literal as the lake. Terraform does not accept var. here.
  # Distinct from the bucket's object lifecycle_rule blocks.
  lifecycle {
    prevent_destroy = true
  }

  depends_on = [
    google_project_service.bigquery,
  ]
}
