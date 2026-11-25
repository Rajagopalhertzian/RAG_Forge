# CloudWatch Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "kms_key_id" {
  description = "KMS key ID for log encryption"
  type        = string
  default     = ""
}

variable "log_groups" {
  description = "Map of log group names"
  type        = map(string)
}

variable "alarms" {
  description = "Map of alarm configurations"
  type = map(object({
    name                    = string
    description             = string
    metric_name             = string
    namespace               = string
    statistic               = string
    period                  = number
    evaluation_periods      = number
    threshold               = number
    comparison_operator     = string
    dimensions              = map(string)
  }))
}

variable "cost_alarms" {
  description = "Map of cost alarm configurations"
  type = map(object({
    name                    = string
    description             = string
    metric_name             = string
    namespace               = string
    statistic               = string
    period                  = number
    evaluation_periods      = number
    threshold               = number
    comparison_operator     = string
    dimensions              = map(string)
  }))
  default = {}
}

variable "alarm_actions" {
  description = "Alarm action ARNs"
  type        = list(string)
  default     = []
}

variable "ok_actions" {
  description = "OK action ARNs"
  type        = list(string)
  default     = []
}

variable "api_target_group_name" {
  description = "API target group name"
  type        = string
}

variable "load_balancer_name" {
  description = "Load balancer name"
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name"
  type        = string
}

variable "db_instance_identifier" {
  description = "RDS DB instance identifier"
  type        = string
}

variable "redis_cache_cluster_id" {
  description = "ElastiCache cluster ID"
  type        = string
}