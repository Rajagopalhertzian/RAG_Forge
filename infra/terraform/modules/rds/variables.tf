# RDS Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "db_subnet_group_name" {
  description = "DB subnet group name"
  type        = string
}

variable "security_group_ids" {
  description = "Security group IDs"
  type        = list(string)
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
}

variable "db_allocated_storage" {
  description = "Initial allocated storage (GB)"
  type        = number
}

variable "db_max_allocated_storage" {
  description = "Maximum allocated storage for autoscaling (GB)"
  type        = number
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
}

variable "db_username" {
  description = "Database master username"
  type        = string
}

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
}

variable "backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
}

variable "backup_window" {
  description = "Backup window (UTC)"
  type        = string
}

variable "maintenance_window" {
  description = "Maintenance window (UTC)"
  type        = string
}

variable "enable_performance_insights" {
  description = "Enable Performance Insights"
  type        = bool
}

variable "performance_insights_retention" {
  description = "Performance Insights retention period in days"
  type        = number
}

variable "deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
}

variable "hnsw_m" {
  description = "HNSW M parameter"
  type        = number
}

variable "hnsw_ef_construction" {
  description = "HNSW ef_construction parameter"
  type        = number
}

variable "hnsw_ef_search" {
  description = "HNSW ef_search parameter"
  type        = number
}