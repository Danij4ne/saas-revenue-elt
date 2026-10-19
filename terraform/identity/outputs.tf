output "pipeline_service_account_email" {
  description = "Email of the pipeline SA. The app root reads this account via data source."
  value       = google_service_account.pipeline.email
}

output "github_deploy_service_account_email" {
  description = "Email of the CD SA. Paste into GitHub Environment var GCP_DEPLOY_SA."
  value       = google_service_account.github_deploy.email
}

output "github_wif_provider_name" {
  description = "Full resource name of the GitHub OIDC provider. Paste into GitHub Environment var GCP_WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}
