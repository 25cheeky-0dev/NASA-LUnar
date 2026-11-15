terraform {
  required_version = ">= 1.8"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 7.0" }
  }
}
provider "google" { project = var.project_id
  region = var.region
}
variable "project_id" { type = string }
variable "region" { type = string
  default = "us-central1"
}
variable "environment" { type = string
  default = "dev"
  validation { condition = contains(["dev", "prod"], var.environment)
    error_message = "Use separate dev or prod environments."
  }
}
variable "image" { type = string }
variable "billing_account" { type = string }
variable "invoker_email" { type = string }
variable "monthly_budget_usd" { type = number
  default = 25
  validation { condition = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 25
    error_message = "This release is authorized for at most USD 25/month."
  }
}
variable "gemini_model" { type = string
  default = ""
}
variable "gemini_secret_version" { type = string
  default = ""
}
locals { name = "wispr-${var.environment}" }
resource "google_project_service" "api" {
  for_each = toset(["run.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com", "storage.googleapis.com", "secretmanager.googleapis.com", "monitoring.googleapis.com", "billingbudgets.googleapis.com"])
  service = each.value
  disable_on_destroy = false
}
resource "google_service_account" "runtime" {
  account_id = "${local.name}-runtime"
  display_name = "WISPR bounded scientific runtime"
}
resource "google_service_account" "builder" {
  account_id = "${local.name}-builder"
  display_name = "WISPR container builder"
}
resource "google_artifact_registry_repository" "images" {
  location = var.region
  repository_id = local.name
  format = "DOCKER"
  depends_on = [google_project_service.api]
  cleanup_policy_dry_run = true
}
resource "google_artifact_registry_repository_iam_member" "builder" {
  location = var.region
  repository = google_artifact_registry_repository.images.name
  role = "roles/artifactregistry.writer"
  member = "serviceAccount:${google_service_account.builder.email}"
}
resource "google_project_iam_member" "builder_logs" {
  project = var.project_id
  role = "roles/logging.logWriter"
  member = "serviceAccount:${google_service_account.builder.email}"
}
resource "google_storage_bucket" "science" {
  name = "${var.project_id}-${local.name}-science"
  location = var.region
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  force_destroy = false
  versioning { enabled = true }
}
resource "google_storage_bucket" "evidence" {
  name = "${var.project_id}-${local.name}-evidence"
  location = var.region
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  force_destroy = false
}
resource "google_storage_bucket" "build" {
  name = "${var.project_id}-${local.name}-build"
  location = var.region
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  force_destroy = false
  lifecycle_rule { condition { age = 7 }
    action { type = "Delete" }
  }
}
resource "google_storage_bucket_iam_member" "build_read" {
  bucket = google_storage_bucket.build.name
  role = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.builder.email}"
}
resource "google_storage_bucket_iam_member" "science_read" {
  bucket = google_storage_bucket.science.name
  role = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_storage_bucket_iam_member" "evidence_access" {
  for_each = toset(["roles/storage.objectCreator", "roles/storage.objectViewer"])
  bucket = google_storage_bucket.evidence.name
  role = each.value
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_secret_manager_secret" "gemini" {
  secret_id = "${local.name}-gemini"
  replication { auto {} }
  depends_on = [google_project_service.api]
}
resource "google_secret_manager_secret_iam_member" "gemini" {
  secret_id = google_secret_manager_secret.gemini.id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_cloud_run_v2_service" "app" {
  name = local.name
  location = var.region
  deletion_protection = true
  ingress = "INGRESS_TRAFFIC_ALL"
  template {
    service_account = google_service_account.runtime.email
    timeout = "180s"
    max_instance_request_concurrency = 8
    scaling { min_instance_count = 0
      max_instance_count = 1
    }
    volumes { name = "science"
      gcs { bucket = google_storage_bucket.science.name
        read_only = true
      }
    }
    containers {
      image = var.image
      resources { limits = { cpu = "1", memory = "1Gi" }
        cpu_idle = true
        startup_cpu_boost = false
      }
      ports { container_port = 8080 }
      volume_mounts { name = "science"
        mount_path = "/science"
      }
      env { name = "WISPR_GLOBAL_ROOT"
        value = "/science/lunar-v1"
      }
      env { name = "WISPR_EVIDENCE_BUCKET"
        value = google_storage_bucket.evidence.name
      }
      env { name = "CELESTIAL_CACHE_DIR"
        value = "/tmp/celestial"
      }
      env { name = "GEMINI_MODEL"
        value = var.gemini_model
      }
      dynamic "env" {
        for_each = var.gemini_secret_version == "" ? [] : [var.gemini_secret_version]
        content { name = "GEMINI_API_KEY"
          value_source { secret_key_ref { secret = google_secret_manager_secret.gemini.secret_id
            version = env.value
          } }
        }
      }
      startup_probe { http_get { path = "/health" }
        initial_delay_seconds = 5
        period_seconds = 10
        failure_threshold = 12
      }
      liveness_probe { http_get { path = "/health" }
        period_seconds = 30
      }
    }
  }
  depends_on = [google_project_service.api, google_storage_bucket_iam_member.science_read, google_storage_bucket_iam_member.evidence_access]
}
resource "google_cloud_run_v2_service_iam_member" "user" {
  location = var.region
  name = google_cloud_run_v2_service.app.name
  role = "roles/run.invoker"
  member = "user:${var.invoker_email}"
}
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name = "${local.name} USD25 operating envelope"
  budget_filter { projects = ["projects/${data.google_project.current.number}"] }
  amount { specified_amount { currency_code = "USD"
    units = tostring(var.monthly_budget_usd)
  } }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.8 }
  threshold_rules { threshold_percent = 1.0 }
}
data "google_project" "current" { project_id = var.project_id }
output "service_url" { value = google_cloud_run_v2_service.app.uri }
output "science_bucket" { value = google_storage_bucket.science.name }
output "evidence_bucket" { value = google_storage_bucket.evidence.name }
output "builder_service_account" { value = google_service_account.builder.email }
