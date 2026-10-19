variable "gcp_project_id" {
  description = "GCP project ID where Terraform will create resources."
  type        = string
}

variable "gcp_region" {
  description = "Default GCP region for regional resources."
  type        = string
}

variable "gcp_location" {
  description = "Location for GCS and BigQuery resources."
  type        = string
}

variable "bucket_name" {
  description = "Globally unique name for the data lake bucket."
  type        = string
}

variable "bucket_storage_class" {
  description = "Storage class for the data lake bucket."
  type        = string
  default     = "STANDARD"
}

variable "environment" {
  description = "Deployment environment. Required via envs/dev.tfvars or envs/prod.tfvars — no default (a silent default labeled the data-bearing stack as dev)."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be \"dev\" or \"prod\"."
  }
}

variable "github_repository" {
  description = "GitHub OWNER/REPO. Still required in the CD var-file (same shape as terraform/identity); WIF itself lives in terraform/identity."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be OWNER/REPO (letters, digits, _, ., -)."
  }
}

variable "tfstate_bucket_name" {
  description = "Existing GCS bucket that holds Terraform state (not the data lake). Still required in the CD var-file; objectAdmin is granted in terraform/identity. Not interpolated into backend.tf."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.tfstate_bucket_name))
    error_message = "tfstate_bucket_name must be a valid GCS bucket name."
  }
}

variable "artifact_registry_repository_id" {
  description = "Artifact Registry Docker repository ID. Same id in each GCP project; not a global bucket name."
  type        = string
  default     = "saas-revenue-app"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,61}[a-z0-9]$", var.artifact_registry_repository_id))
    error_message = "artifact_registry_repository_id must be 6-63 characters and match RFC1035 (start with a letter)."
  }
}

variable "ar_promote_reader_member" {
  description = "IAM member granted artifactregistry.reader on this env's AR so prod CD can pull the sandbox image. Required serviceAccount:email on env=dev (prod github-deploy). Must be empty on env=prod."
  type        = string
  default     = ""

  validation {
    condition     = var.ar_promote_reader_member == "" || can(regex("^serviceAccount:[^@]+@.+$", var.ar_promote_reader_member))
    error_message = "ar_promote_reader_member must be empty or serviceAccount:<email>."
  }
}

variable "app_image_tag" {
  description = "Docker tag the Cloud Run Job pins. CD writes github.sha. Local apply: a tag already pushed to Artifact Registry."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", var.app_image_tag))
    error_message = "app_image_tag must be a Docker tag (start with a letter or digit; letters, digits, _, ., -)."
  }
}

variable "cloud_run_job_name" {
  description = "Cloud Run Job name. Same id in each GCP project. RFC1035."
  type        = string
  default     = "saas-revenue-elt"

  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.cloud_run_job_name))
    error_message = "cloud_run_job_name must be 1-63 characters and match RFC1035 (start with a letter)."
  }
}

variable "github_deploy_sa_account_id" {
  description = "GCP service account ID (not email) for CD terraform apply via WIF. 6-30 chars, RFC1035."
  type        = string
  default     = "github-deploy"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.github_deploy_sa_account_id))
    error_message = "github_deploy_sa_account_id must be 6-30 characters and match RFC1035 (start with a letter)."
  }
}

variable "pipeline_sa_account_id" {
  description = "GCP service account ID (not email) for the ELT pipeline. 6-30 chars, RFC1035."
  type        = string
  default     = "elt-pipeline"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.pipeline_sa_account_id))
    error_message = "pipeline_sa_account_id must be 6-30 characters and match RFC1035 (start with a letter)."
  }
}

variable "scheduler_sa_account_id" {
  description = "GCP service account ID (not email) for Cloud Scheduler to invoke the Cloud Run Job. 6-30 chars, RFC1035. Not elt-pipeline (DECISIONS #18)."
  type        = string
  default     = "elt-scheduler"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.scheduler_sa_account_id))
    error_message = "scheduler_sa_account_id must be 6-30 characters and match RFC1035 (start with a letter)."
  }
}

variable "scheduler_job_name" {
  description = "Cloud Scheduler job name. Distinct from the Cloud Run Job name. RFC1035."
  type        = string
  default     = "saas-revenue-elt-daily"

  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.scheduler_job_name))
    error_message = "scheduler_job_name must be 1-63 characters and match RFC1035 (start with a letter)."
  }
}

variable "scheduler_schedule" {
  description = "Unix cron (five fields) for the Scheduler job. Default is daily 09:00 UTC."
  type        = string
  default     = "0 9 * * *"

  validation {
    condition     = can(regex("^\\S+\\s+\\S+\\s+\\S+\\s+\\S+\\s+\\S+$", var.scheduler_schedule))
    error_message = "scheduler_schedule must be a five-field Unix cron expression."
  }
}

variable "scheduler_time_zone" {
  description = "IANA time zone for scheduler_schedule (tz database). Default Etc/UTC is unambiguous."
  type        = string
  default     = "Etc/UTC"

  validation {
    condition     = length(var.scheduler_time_zone) >= 3 && length(var.scheduler_time_zone) <= 64
    error_message = "scheduler_time_zone must be an IANA tz database name (e.g. Etc/UTC, Europe/Madrid)."
  }
}

variable "scheduler_paused" {
  description = "If true (default), the cron exists but does not fire. Unpause is an explicit tfvars change."
  type        = bool
  default     = true
}

variable "alert_email" {
  description = "Email for the Job-failed notification channel. Required via tfvars / CD (GCP_ALERT_EMAIL). Not a secret; still not committed."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", var.alert_email))
    error_message = "alert_email must be a single email address."
  }
}

variable "lake_lifecycle_object_prefix" {
  description = "GCS object prefix for data-lake lifecycle rules (live cool + noncurrent delete). Must end with /."
  type        = string
  default     = "raw/"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9/_-]*$", var.lake_lifecycle_object_prefix)) && endswith(var.lake_lifecycle_object_prefix, "/")
    error_message = "lake_lifecycle_object_prefix must be a non-empty GCS prefix ending with /."
  }
}

variable "lake_lifecycle_nearline_age_days" {
  description = "Age in days (since object creation) when live Standard objects under the prefix move to Nearline."
  type        = number
  default     = 30

  validation {
    condition     = var.lake_lifecycle_nearline_age_days >= 30
    error_message = "lake_lifecycle_nearline_age_days must be at least 30 (Nearline minimum storage duration)."
  }
}

variable "lake_lifecycle_coldline_age_days" {
  description = "Age in days (since object creation) when live Nearline objects under the prefix move to Coldline."
  type        = number
  default     = 90

  validation {
    condition     = var.lake_lifecycle_coldline_age_days >= 90
    error_message = "lake_lifecycle_coldline_age_days must be at least 90 (Coldline minimum storage duration)."
  }
}

variable "lake_lifecycle_noncurrent_days" {
  description = "Days after a version becomes noncurrent before it is deleted (undelete window; not the live object)."
  type        = number
  default     = 7

  validation {
    condition     = var.lake_lifecycle_noncurrent_days >= 1
    error_message = "lake_lifecycle_noncurrent_days must be at least 1."
  }
}

variable "lake_lifecycle_abort_incomplete_days" {
  description = "Age in days after which incomplete multipart uploads are aborted."
  type        = number
  default     = 1

  validation {
    condition     = var.lake_lifecycle_abort_incomplete_days >= 1
    error_message = "lake_lifecycle_abort_incomplete_days must be at least 1."
  }
}

variable "raw_partition_expiration_days" {
  description = "Partition expiration for new tables in dataset raw (days). Existing tables are not retroactive."
  type        = number
  default     = 365

  validation {
    condition     = var.raw_partition_expiration_days >= 1
    error_message = "raw_partition_expiration_days must be at least 1."
  }
}
