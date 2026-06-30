variable "project_id" {
  type        = string
  description = "The GCP project ID"
}

variable "region" {
  type        = string
  description = "The GCP region"
}

variable "cluster_name" {
  type        = string
  description = "Name of the GKE cluster"
}

variable "bucket_name" {
  type        = string
  description = "Name of the GCS bucket"
}

variable "repo_name" {
  type        = string
  description = "Name of the Artifact Registry repository"
}
