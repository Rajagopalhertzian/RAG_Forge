# ContextForge Terraform Variables

variable "environment" {
  description = "Environment name (staging, prod)"
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "Environment must be 'staging' or 'prod'."
  }
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# =============================================================================
# VPC Configuration
# =============================================================================
variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDR blocks"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDR blocks"
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

variable "database_subnet_cidrs" {
  description = "Database subnet CIDR blocks"
  type        = list(string)
  default     = ["10.0.21.0/24", "10.0.22.0/24", "10.0.23.0/24"]
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnet internet access"
  type        = bool
  default     = true
}

variable "enable_vpc_endpoints" {
  description = "Enable VPC endpoints for AWS services"
  type        = bool
  default     = true
}

# =============================================================================
# Security Configuration
# =============================================================================
variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to access ALB"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "mcp_allowed_ips" {
  description = "IP addresses allowed to access MCP gateway"
  type        = list(string)
  default     = []
}

variable "bastion_ingress_cidrs" {
  description = "CIDR blocks allowed for bastion/SSH access"
  type        = list(string)
  default     = []
}

variable "cors_origins" {
  description = "Allowed CORS origins for S3 buckets"
  type        = list(string)
  default     = ["https://app.contextforge.dev", "https://staging.contextforge.dev"]
}

# =============================================================================
# RDS Configuration
# =============================================================================
variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.r6g.xlarge"
}

variable "db_allocated_storage" {
  description = "Initial allocated storage (GB)"
  type        = number
  default     = 100
}

variable "db_max_allocated_storage" {
  description = "Maximum allocated storage for autoscaling (GB)"
  type        = number
  default     = 1000
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "16.3"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "postgres"
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "contextforge"
}

variable "db_multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
  default     = true
}

variable "db_backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 30
}

variable "db_backup_window" {
  description = "Backup window (UTC)"
  type        = string
  default     = "03:00-04:00"
}

variable "db_maintenance_window" {
  description = "Maintenance window (UTC)"
  type        = string
  default     = "sun:04:00-sun:05:00"
}

variable "db_enable_performance_insights" {
  description = "Enable Performance Insights"
  type        = bool
  default     = true
}

variable "db_performance_insights_retention" {
  description = "Performance Insights retention period in days"
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
  default     = true
}

variable "db_rotation_lambda_arn" {
  description = "Lambda ARN for secret rotation"
  type        = string
  default     = ""
}

# HNSW Index Configuration
variable "hnsw_m" {
  description = "HNSW M parameter (max connections per layer)"
  type        = number
  default     = 16
}

variable "hnsw_ef_construction" {
  description = "HNSW ef_construction parameter"
  type        = number
  default     = 64
}

variable "hnsw_ef_search" {
  description = "HNSW ef_search parameter"
  type        = number
  default     = 40
}

# =============================================================================
# ElastiCache Redis Configuration
# =============================================================================
variable "redis_engine_version" {
  description = "Redis engine version"
  type        = string
  default     = "7.2"
}

variable "redis_node_type" {
  description = "Redis node type"
  type        = string
  default     = "cache.r6g.xlarge"
}

variable "redis_num_node_groups" {
  description = "Number of node groups (shards)"
  type        = number
  default     = 2
}

variable "redis_replicas_per_node_group" {
  description = "Number of replicas per node group"
  type        = number
  default     = 1
}

variable "redis_snapshot_retention" {
  description = "Snapshot retention limit (days)"
  type        = number
  default     = 7
}

variable "redis_snapshot_window" {
  description = "Snapshot window (UTC)"
  type        = string
  default     = "03:00-04:00"
}

variable "redis_maintenance_window" {
  description = "Maintenance window (UTC)"
  type        = string
  default     = "sun:05:00-sun:06:00"
}

# =============================================================================
# ECS Service Configuration
# =============================================================================
variable "api_cpu" {
  description = "API service CPU units"
  type        = number
  default     = 2048
}

variable "api_memory" {
  description = "API service memory (MiB)"
  type        = number
  default     = 4096
}

variable "api_desired_count" {
  description = "API service desired count"
  type        = number
  default     = 3
}

variable "api_min_capacity" {
  description = "API service minimum capacity"
  type        = number
  default     = 2
}

variable "api_max_capacity" {
  description = "API service maximum capacity"
  type        = number
  default     = 10
}

variable "mcp_cpu" {
  description = "MCP service CPU units"
  type        = number
  default     = 1024
}

variable "mcp_memory" {
  description = "MCP service memory (MiB)"
  type        = number
  default     = 2048
}

variable "mcp_desired_count" {
  description = "MCP service desired count"
  type        = number
  default     = 2
}

variable "mcp_min_capacity" {
  description = "MCP service minimum capacity"
  type        = number
  default     = 1
}

variable "mcp_max_capacity" {
  description = "MCP service maximum capacity"
  type        = number
  default     = 5
}

variable "worker_cpu" {
  description = "Worker service CPU units"
  type        = number
  default     = 4096
}

variable "worker_memory" {
  description = "Worker service memory (MiB)"
  type        = number
  default     = 8192
}

variable "worker_desired_count" {
  description = "Worker service desired count"
  type        = number
  default     = 3
}

variable "worker_min_capacity" {
  description = "Worker service minimum capacity"
  type        = number
  default     = 2
}

variable "worker_max_capacity" {
  description = "Worker service maximum capacity"
  type        = number
  default     = 20
}

# =============================================================================
# WAF Configuration
# =============================================================================
variable "waf_enabled" {
  description = "Enable WAF"
  type        = bool
  default     = true
}

variable "waf_rate_limit" {
  description = "WAF rate limit (requests per 5 minutes)"
  type        = number
  default     = 1000
}

variable "waf_geo_block_countries" {
  description = "Countries to block (ISO 3166-1 alpha-2 codes)"
  type        = list(string)
  default     = []
}

# =============================================================================
# SSL Configuration
# =============================================================================
variable "ssl_certificate_arn" {
  description = "ACM SSL certificate ARN"
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for certificate validation"
  type        = string
  default     = ""
}

# =============================================================================
# External Secrets (injected at deploy time)
# =============================================================================
variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_access_key_id" {
  description = "AWS access key ID for Bedrock"
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_secret_access_key" {
  description = "AWS secret access key for Bedrock"
  type        = string
  sensitive   = true
  default     = ""
}

variable "mcp_cert" {
  description = "MCP TLS certificate"
  type        = string
  sensitive   = true
  default     = ""
}

variable "mcp_key" {
  description = "MCP TLS private key"
  type        = string
  sensitive   = true
  default     = ""
}