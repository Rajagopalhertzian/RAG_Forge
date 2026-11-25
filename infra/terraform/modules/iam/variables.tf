# IAM Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "account_id" {
  description = "AWS account ID"
  type        = string
}

variable "github_org" {
  description = "GitHub organization"
  type        = string
  default     = "contextforge"
}

variable "github_repo" {
  description = "GitHub repository"
  type        = string
  default     = "contextforge"
}

variable "ecs_task_permissions" {
  description = "ECS task permissions"
  type        = list(string)
}

variable "cicd_deploy_permissions" {
  description = "CI/CD deploy permissions"
  type        = list(string)
}

variable "terraform_permissions" {
  description = "Terraform permissions"
  type        = list(string)
}