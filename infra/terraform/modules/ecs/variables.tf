# ECS Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs"
  type        = list(string)
}

variable "task_role_arn" {
  description = "ECS task role ARN"
  type        = string
}

variable "execution_role_arn" {
  description = "ECS execution role ARN"
  type        = string
}

variable "ecr_repositories" {
  description = "Map of ECR repository names"
  type        = map(string)
}

variable "api_service" {
  description = "API service configuration"
  type = object({
    name                = string
    cpu                 = number
    memory              = number
    desired_count       = number
    min_capacity        = number
    max_capacity        = number
    container_port      = number
    health_check_path   = string
    environment_variables = map(string)
    secrets = list(object({
      name      = string
      valueFrom = string
    }))
  })
}

variable "mcp_service" {
  description = "MCP service configuration"
  type = object({
    name                = string
    cpu                 = number
    memory              = number
    desired_count       = number
    min_capacity        = number
    max_capacity        = number
    container_port      = number
    health_check_path   = string
    environment_variables = map(string)
    secrets = list(object({
      name      = string
      valueFrom = string
    }))
  })
}

variable "worker_service" {
  description = "Worker service configuration"
  type = object({
    name                = string
    cpu                 = number
    memory              = number
    desired_count       = number
    min_capacity        = number
    max_capacity        = number
    container_port      = number
    health_check_path   = string
    environment_variables = map(string)
    secrets = list(object({
      name      = string
      valueFrom = string
    }))
  })
}