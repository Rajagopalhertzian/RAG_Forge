# ElastiCache Redis Cluster Module for ContextForge

# =============================================================================
# KMS Key for ElastiCache Encryption
# =============================================================================
resource "aws_kms_key" "elasticache" {
  description             = "KMS key for ElastiCache encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Allow administration of the key"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action = [
          "kms:*"
        ]
        Resource = "*"
      },
      {
        Sid    = "Allow ElastiCache to use the key"
        Effect = "Allow"
        Principal = {
          Service = "elasticache.amazonaws.com"
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name = "contextforge-${var.environment}-elasticache-key"
  }
}

resource "aws_kms_alias" "elasticache" {
  name          = "alias/contextforge-${var.environment}-elasticache"
  target_key_id = aws_kms_key.elasticache.key_id
}

# =============================================================================
# ElastiCache Parameter Group
# =============================================================================
resource "aws_elasticache_parameter_group" "main" {
  name        = "contextforge-${var.environment}-redis7"
  family      = "redis7"
  description = "Parameter group for ContextForge Redis 7"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  parameter {
    name  = "timeout"
    value = "300"
  }

  parameter {
    name  = "tcp-keepalive"
    value = "60"
  }

  parameter {
    name  = "lazyfree-lazy-eviction"
    value = "yes"
  }

  parameter {
    name  = "lazyfree-lazy-expire"
    value = "yes"
  }

  parameter {
    name  = "lazyfree-lazy-server-del"
    value = "yes"
  }

  parameter {
    name  = "replica-lazy-flush"
    value = "yes"
  }

  tags = {
    Name = "contextforge-${var.environment}-redis7-params"
  }
}

# =============================================================================
# ElastiCache Replication Group (Cluster Mode)
# =============================================================================
resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = "contextforge-${var.environment}"
  replication_group_description = "ContextForge Redis Cluster for ${var.environment}"

  engine                     = "redis"
  engine_version             = var.engine_version

  node_type                  = var.node_type
  number_of_node_groups      = var.num_node_groups
  replicas_per_node_group    = var.replicas_per_node_group

  parameter_group_name       = aws_elasticache_parameter_group.main.name

  subnet_group_name          = var.subnet_group_name
  security_group_ids         = var.security_group_ids

  at_rest_encryption_enabled = var.at_rest_encryption
  transit_encryption_enabled = var.transit_encryption
  auth_token                 = var.auth_token

  automatic_failover_enabled = var.automatic_failover
  multi_az_enabled           = var.multi_az

  snapshot_retention_limit   = var.snapshot_retention_limit
  snapshot_window            = var.snapshot_window
  maintenance_window         = var.maintenance_window

  log_delivery_configuration {
    destination_type = "cloudwatch-logs"
    log_type         = "slow-log"
    destination_details {
      cloudwatch_logs {
        log_group = aws_cloudwatch_log_group.redis_slow.name
      }
    }
  }

  log_delivery_configuration {
    destination_type = "cloudwatch-logs"
    log_type         = "engine-log"
    destination_details {
      cloudwatch_logs {
        log_group = aws_cloudwatch_log_group.redis_engine.name
      }
    }
  }

  tags = {
    Name = "contextforge-${var.environment}-elasticache"
  }
}

# =============================================================================
# CloudWatch Log Groups
# =============================================================================
resource "aws_cloudwatch_log_group" "redis_slow" {
  name              = "/aws/elasticache/contextforge-${var.environment}/slow-log"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.elasticache.arn
}

resource "aws_cloudwatch_log_group" "redis_engine" {
  name              = "/aws/elasticache/contextforge-${var.environment}/engine-log"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.elasticache.arn
}

# =============================================================================
# Outputs
# =============================================================================
output "replication_group_id" {
  description = "Replication group ID"
  value       = aws_elasticache_replication_group.main.id
}

output "redis_endpoint" {
  description = "Primary endpoint"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
  sensitive   = true
}

output "redis_port" {
  description = "Primary endpoint port"
  value       = aws_elasticache_replication_group.main.primary_endpoint_port
}

output "reader_endpoint" {
  description = "Reader endpoint"
  value       = aws_elasticache_replication_group.main.reader_endpoint_address
  sensitive   = true
}

output "reader_endpoint_port" {
  description = "Reader endpoint port"
  value       = aws_elasticache_replication_group.main.reader_endpoint_port
}

output "cache_cluster_id" {
  description = "Cache cluster ID (for CloudWatch)"
  value       = aws_elasticache_replication_group.main.cluster_enabled ? aws_elasticache_replication_group.main.member_clusters[0] : null
}

output "kms_key_arn" {
  description = "KMS key ARN"
  value       = aws_kms_key.elasticache.arn
}

output "parameter_group_name" {
  description = "Parameter group name"
  value       = aws_elasticache_parameter_group.main.name
}