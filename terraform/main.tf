provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. GCS Bucket
resource "google_storage_bucket" "benchmark_bucket" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = true
}

# 2. Artifact Registry Repository
resource "google_artifact_registry_repository" "benchmark_repo" {
  repository_id = var.repo_name
  location      = var.region
  format        = "DOCKER"
  description   = "Docker repository for SWE-bench and Sandbox base images"
}

# 3. GKE Cluster
resource "google_container_cluster" "benchmark_cluster" {
  name     = var.cluster_name
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1
}

resource "google_container_node_pool" "primary_nodes" {
  name       = "primary-node-pool"
  cluster    = google_container_cluster.benchmark_cluster.name
  location   = var.region
  
  # node_count is per-zone in a regional cluster. 
  # So 1 per zone * ~3 zones = ~3 nodes total.
  node_count = 1

  node_config {
    machine_type = "e2-standard-4"
    
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
}
