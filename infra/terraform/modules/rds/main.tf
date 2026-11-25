# RDS PostgreSQL with pgvector Module for ContextForge

# =============================================================================
# KMS Key for RDS Encryption
# =============================================================================
resource "aws_kms_key" "rds" {
  description             = "KMS key for RDS encryption"
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
        Sid    = "Allow RDS to use the key"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
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
    Name = "contextforge-${var.environment}-rds-key"
  }
}

resource "aws_kms_alias" "rds" {
  name          = "alias/contextforge-${var.environment}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# =============================================================================
# DB Parameter Group (with HNSW configuration)
# =============================================================================
resource "aws_db_parameter_group" "main" {
  name        = "contextforge-${var.environment}-pg16"
  family      = "postgres16"
  description = "Parameter group for ContextForge PostgreSQL 16 with pgvector HNSW"

  parameter {
    name  = "shared_preload_libraries"
    value = "pgvector"
  }

  parameter {
    name  = "max_connections"
    value = "200"
  }

  parameter {
    name  = "shared_buffers"
    value = "{DBInstanceClassMemory/4}"
  }

  parameter {
    name  = "effective_cache_size"
    value = "{DBInstanceClassMemory*3/4}"
  }

  parameter {
    name  = "maintenance_work_mem"
    value = "256MB"
  }

  parameter {
    name  = "work_mem"
    value = "16MB"
  }

  parameter {
    name  = "random_page_cost"
    value = "1.1"
  }

  parameter {
    name  = "effective_io_concurrency"
    value = "200"
  }

  # HNSW index parameters
  parameter {
    name  = "hnsw.ef_search"
    value = var.hnsw_ef_search
  }

  tags = {
    Name = "contextforge-${var.environment}-pg16-params"
  }
}

# =============================================================================
# DB Subnet Group (created in VPC module, referenced here)
# =============================================================================
# Using the subnet group from VPC module

# =============================================================================
# RDS Instance
# =============================================================================
resource "aws_db_instance" "main" {
  identifier             = "contextforge-${var.environment}"
  engine                 = "postgres"
  engine_version         = var.db_engine_version
  instance_class         = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  max_allocated_storage  = var.db_max_allocated_storage
  storage_type           = "gp3"
  storage_encrypted      = true
  kms_key_id             = aws_kms_key.rds.arn

  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = var.security_group_ids

  multi_az               = var.multi_az
  publicly_accessible    = false

  backup_retention_period = var.backup_retention_period
  backup_window          = var.backup_window
  maintenance_window     = var.maintenance_window

  enable_performance_insights = var.enable_performance_insights
  performance_insights_retention_period = var.performance_insights_retention
  performance_insights_kms_key_id = aws_kms_key.rds.arn

  deletion_protection    = var.deletion_protection
  skip_final_snapshot    = false
  final_snapshot_identifier = "contextforge-${var.environment}-final-snapshot-${formatdate("YYYYMMDD", timestamp())}"

  parameter_group_name   = aws_db_parameter_group.main.name

  monitoring_interval    = 60
  monitoring_role_arn    = aws_iam_role.rds_monitoring.arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = {
    Name = "contextforge-${var.environment}-rds"
  }
}

# =============================================================================
# IAM Role for RDS Enhanced Monitoring
# =============================================================================
resource "aws_iam_role" "rds_monitoring" {
  name = "contextforge-${var.environment}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "monitoring.rds.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# =============================================================================
# Read Replica (for prod)
# =============================================================================
resource "aws_db_instance" "replica" {
  count = var.multi_az && var.environment == "prod" ? 1 : 0

  identifier             = "contextforge-${var.environment}-replica"
  replicate_source_db    = aws_db_instance.main.identifier
  instance_class         = var.db_instance_class
  storage_type           = "gp3"
  storage_encrypted      = true
  kms_key_id             = aws_kms_key.rds.arn

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = var.security_group_ids

  multi_az               = false
  publicly_accessible    = false

  deletion_protection    = var.deletion_protection
  skip_final_snapshot    = true

  monitoring_interval    = 60
  monitoring_role_arn    = aws_iam_role.rds_monitoring.arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = {
    Name = "contextforge-${var.environment}-rds-replica"
  }
}

# =============================================================================
# CloudWatch Log Group
# =============================================================================
resource "aws_cloudwatch_log_group" "rds" {
  name              = "/aws/rds/contextforge-${var.environment}/postgresql"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.rds.arn

  tags = {
    Name = "contextforge-${var.environment}-rds-logs"
  }
}

# =============================================================================
# Outputs
# =============================================================================
output "db_instance_identifier" {
  description = "RDS instance identifier"
  value       = aws_db_instance.main.id
}

output "db_endpoint" {
  description = "RDS endpoint"
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "db_port" {
  description = "RDS port"
  value       = aws_db_instance.main.port
}

output "db_arn" {
  description = "RDS ARN"
  value       = aws_db_instance.main.arn
}

output "db_parameter_group_name" {
  description = "DB parameter group name"
  value       = aws_db_parameter_group.main.name
}

output "kms_key_arn" {
  description = "KMS key ARN"
  value       = aws_kms_key.rds.arn
}

output "replica_endpoint" {
  description = "Read replica endpoint"
  value       = var.multi_az && var.environment == "prod" ? aws_db_instance.replica[0].endpoint : null
  sensitive   = true
}