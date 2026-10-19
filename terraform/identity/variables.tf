variable "gcp_project_id" {
  description = "GCP project ID where identity-root SAs and project IAM live."
  type        = string
}

variable "gcp_region" {
  description = "Default GCP region for the Google provider (no regional resources here)."
  type        = string
}

variable "github_repository" {
  description = "GitHub repo allowed to impersonate github-deploy via WIF (OWNER/REPO)."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be OWNER/REPO (letters, digits, _, ., -)."
  }
}

variable "tfstate_bucket_name" {
  description = "Existing GCS bucket that holds Terraform state (not the data lake). Grants github-deploy objectAdmin."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.tfstate_bucket_name))
    error_message = "tfstate_bucket_name must be a valid GCS bucket name."
  }
}

variable "github_deploy_sa_account_id" {
  description = "GCP service account ID (not email) for CD terraform apply via WIF."
  type        = string
  default     = "github-deploy"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.github_deploy_sa_account_id))
    error_message = "github_deploy_sa_account_id must be 6-30 characters and match RFC1035 (start with a letter)."
  }
}

variable "pipeline_sa_account_id" {
  description = "GCP service account ID (not email) for the ELT pipeline."
  type        = string
  default     = "elt-pipeline"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.pipeline_sa_account_id))
    error_message = "pipeline_sa_account_id must be 6-30 characters and match RFC1035 (start with a letter)."
  }
}
