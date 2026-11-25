# ElastiCache Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "subnet_group_name" {
  description = "ElastiCache subnet group name"
  type        = string
}

variable "security_group_ids" {
  description = "Security group IDs"
  type        = list(string)
}

variable "engine_version" {
  description = "Redis engine version"
  type        = string
}

variable "node_type" {
  description = "Redis node type"
  type        = string
}

variable "num_node_groups" {
  description = "Number of node groups (shards)"
  type        = number
}

variable "replicas_per_node_group" {
  description = "Number of replicas per node group"
  type        = number
}

variable "auth_token" {
  description = "Redis auth token"
  type        = string
  sensitive   = true
}

variable "at_rest_encryption" {
  description = "Enable at-rest encryption"
  type        = bool
}

variable "transit_encryption" {
  description = "Enable in-transit encryption"
  type        = bool
}

variable "automatic_failover" {
  description = "Enable automatic failover"
  type        = bool
}

variable "multi_az" {
  description = "Enable Multi-AZ"
  type        = bool
}

variable "snapshot_retention_limit" {
  description = "Snapshot retention limit (days)"
  type        = number
}

variable "snapshot_window" {
  description = "Snapshot window (UTC)"
  type        = string
}

variable "maintenance_window" {
  description = "Maintenance window (UTC)"
  type        = string
}