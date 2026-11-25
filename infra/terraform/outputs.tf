# ContextForge Terraform Outputs

# =============================================================================
# VPC Outputs
# =============================================================================
output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = module.vpc.vpc_cidr
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnet_ids
}

output "database_subnet_ids" {
  description = "Database subnet IDs"
  value       = module.vpc.database_subnet_ids
}

output "nat_gateway_ids" {
  description = "NAT Gateway IDs"
  value       = module.vpc.nat_gateway_ids
}

# =============================================================================
# Security Group Outputs
# =============================================================================
output "alb_sg_id" {
  description = "ALB security group ID"
  value       = module.security_groups.alb_sg_id
}

output "ecs_sg_id" {
  description = "ECS security group ID"
  value       = module.security_groups.ecs_sg_id
}

output "rds_sg_id" {
  description = "RDS security group ID"
  value       = module.security_groups.rds_sg_id
}

output "elasticache_sg_id" {
  description = "ElastiCache security group ID"
  value       = module.security_groups.elasticache_sg_id
}

# =============================================================================
# RDS Outputs
# =============================================================================
output "db_endpoint" {
  description = "RDS endpoint"
  value       = module.rds.db_endpoint
  sensitive   = true
}

output "db_port" {
  description = "RDS port"
  value       = module.rds.db_port
}

output "db_instance_identifier" {
  description = "RDS instance identifier"
  value       = module.rds.db_instance_identifier
}

output "db_arn" {
  description = "RDS ARN"
  value       = module.rds.db_arn
}

output "db_parameter_group_name" {
  description = "DB parameter group name"
  value       = module.rds.db_parameter_group_name
}

output "replica_endpoint" {
  description = "Read replica endpoint"
  value       = module.rds.replica_endpoint
  sensitive   = true
}

# =============================================================================
# ElastiCache Outputs
# =============================================================================
output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = module.elasticache.redis_endpoint
  sensitive   = true
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = module.elasticache.redis_port
}

output "redis_reader_endpoint" {
  description = "ElastiCache Redis reader endpoint"
  value       = module.elasticache.reader_endpoint
  sensitive   = true
}

output "cache_cluster_id" {
  description = "ElastiCache cluster ID for CloudWatch"
  value       = module.elasticache.cache_cluster_id
}

# =============================================================================
# S3 Outputs
# =============================================================================
output "bucket_names" {
  description = "Map of S3 bucket names"
  value       = module.s3.bucket_names
}

output "bucket_arns" {
  description = "Map of S3 bucket ARNs"
  value       = module.s3.bucket_arns
}

output "terraform_state_bucket" {
  description = "Terraform state bucket name"
  value       = module.s3.bucket_names["terraform_state"]
}

output "terraform_locks_table" {
  description = "Terraform locks DynamoDB table name"
  value       = module.s3.locks_table_name
}

# =============================================================================
# Secrets Manager Outputs
# =============================================================================
output "secret_arns" {
  description = "Map of secret ARNs"
  value       = module.secrets.secret_arns
  sensitive   = true
}

output "secret_names" {
  description = "Map of secret names"
  value       = module.secrets.secret_names
}

# =============================================================================
# IAM Outputs
# =============================================================================
output "ecs_task_role_arn" {
  description = "ECS task role ARN"
  value       = module.iam.ecs_task_role_arn
}

output "ecs_task_role_name" {
  description = "ECS task role name"
  value       = module.iam.ecs_task_role_name
}

output "ecs_execution_role_arn" {
  description = "ECS execution role ARN"
  value       = module.iam.ecs_execution_role_arn
}

output "ecs_execution_role_name" {
  description = "ECS execution role name"
  value       = module.iam.ecs_execution_role_name
}

output "cicd_deploy_role_arn" {
  description = "CI/CD deploy role ARN"
  value       = module.iam.cicd_deploy_role_arn
}

output "terraform_role_arn" {
  description = "Terraform role ARN"
  value       = module.iam.terraform_role_arn
}

output "eval_role_arn" {
  description = "Evaluation role ARN"
  value       = module.iam.eval_role_arn
}

# =============================================================================
# ECS Outputs
# =============================================================================
output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = module.ecs.cluster_arn
}

output "api_blue_target_group_arn" {
  description = "API Blue target group ARN"
  value       = module.ecs.api_blue_target_group_arn
}

output "api_green_target_group_arn" {
  description = "API Green target group ARN"
  value       = module.ecs.api_green_target_group_arn
}

output "mcp_blue_target_group_arn" {
  description = "MCP Blue target group ARN"
  value       = module.ecs.mcp_blue_target_group_arn
}

output "mcp_green_target_group_arn" {
  description = "MCP Green target group ARN"
  value       = module.ecs.mcp_green_target_group_arn
}

output "api_target_group_name" {
  description = "API target group name (for CloudWatch)"
  value       = module.ecs.api_target_group_name
}

output "ecr_api_repository_url" {
  description = "ECR API repository URL"
  value       = module.ecs.ecr_api_repository_url
}

output "ecr_mcp_repository_url" {
  description = "ECR MCP repository URL"
  value       = module.ecs.ecr_mcp_repository_url
}

output "ecr_worker_repository_url" {
  description = "ECR Worker repository URL"
  value       = module.ecs.ecr_worker_repository_url
}

output "api_task_definition_blue_arn" {
  description = "API Blue task definition ARN"
  value       = module.ecs.api_task_definition_blue_arn
}

output "api_task_definition_green_arn" {
  description = "API Green task definition ARN"
  value       = module.ecs.api_task_definition_green_arn
}

output "mcp_task_definition_blue_arn" {
  description = "MCP Blue task definition ARN"
  value       = module.ecs.mcp_task_definition_blue_arn
}

output "mcp_task_definition_green_arn" {
  description = "MCP Green task definition ARN"
  value       = module.ecs.mcp_task_definition_green_arn
}

output "worker_task_definition_arn" {
  description = "Worker task definition ARN"
  value       = module.ecs.worker_task_definition_arn
}

# =============================================================================
# ALB Outputs
# =============================================================================
output "alb_arn" {
  description = "ALB ARN"
  value       = module.alb.load_balancer_arn
}

output "alb_dns_name" {
  description = "ALB DNS name"
  value       = module.alb.load_balancer_dns_name
}

output "alb_name" {
  description = "ALB name"
  value       = module.alb.load_balancer_name
}

output "alb_zone_id" {
  description = "ALB zone ID"
  value       = module.alb.load_balancer_zone_id
}

output "https_listener_arn" {
  description = "HTTPS listener ARN"
  value       = module.alb.https_listener_arn
}

# =============================================================================
# CloudWatch Outputs
# =============================================================================
output "sns_topic_arn" {
  description = "SNS topic ARN for alarms"
  value       = module.cloudwatch.sns_topic_arn
}

output "dashboard_name" {
  description = "CloudWatch dashboard name"
  value       = module.cloudwatch.dashboard_name
}

# =============================================================================
# WAF Outputs
# =============================================================================
output "waf_web_acl_arn" {
  description = "WAF Web ACL ARN"
  value       = module.waf.web_acl_arn
}

output "waf_web_acl_id" {
  description = "WAF Web ACL ID"
  value       = module.waf.web_acl_id
}

output "waf_ip_set_arn" {
  description = "WAF IP Set ARN for MCP allowlist"
  value       = module.waf.ip_set_arn
}