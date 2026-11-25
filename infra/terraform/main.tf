# ContextForge Terraform Configuration
# Main entry point - providers, backend, and module composition

terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }

  backend "s3" {
    # Configured via -backend-config in CI/CD
    # bucket         = "contextforge-terraform-state"
    # key            = "contextforge/${var.environment}/terraform.tfstate"
    # region         = "us-east-1"
    # dynamodb_table = "contextforge-terraform-locks"
    # encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "contextforge"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "platform-team"
    }
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

# =============================================================================
# Data Sources
# =============================================================================
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# =============================================================================
# Random Resources for Unique Names
# =============================================================================
resource "random_id" "suffix" {
  byte_length = 4
}

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!@#$%^&*"
}

resource "random_password" "redis_password" {
  length           = 32
  special          = true
  override_special = "!@#$%^&*"
}

resource "random_password" "secret_key" {
  length           = 64
  special          = true
  override_special = "!@#$%^&*"
}

# =============================================================================
# Module: VPC
# =============================================================================
module "vpc" {
  source = "./modules/vpc"

  environment     = var.environment
  aws_region      = var.aws_region
  vpc_cidr        = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  database_subnet_cidrs = var.database_subnet_cidrs
  enable_nat_gateway   = var.enable_nat_gateway
  enable_vpc_endpoints = var.enable_vpc_endpoints
}

# =============================================================================
# Module: Security Groups
# =============================================================================
module "security_groups" {
  source = "./modules/security_groups"

  environment = var.environment
  vpc_id      = module.vpc.vpc_id

  # Ingress rules
  alb_ingress_cidrs       = var.alb_ingress_cidrs
  mcp_allowed_ips         = var.mcp_allowed_ips
  bastion_ingress_cidrs   = var.bastion_ingress_cidrs
}

# =============================================================================
# Module: RDS PostgreSQL with pgvector
# =============================================================================
module "rds" {
  source = "./modules/rds"

  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  database_subnet_ids   = module.vpc.database_subnet_ids
  security_group_ids    = [module.security_groups.rds_sg_id]

  db_instance_class     = var.db_instance_class
  db_allocated_storage  = var.db_allocated_storage
  db_max_allocated_storage = var.db_max_allocated_storage
  db_engine_version     = var.db_engine_version
  db_username           = var.db_username
  db_password           = random_password.db_password.result
  db_name               = var.db_name

  multi_az              = var.db_multi_az
  backup_retention_period = var.db_backup_retention_period
  backup_window         = var.db_backup_window
  maintenance_window    = var.db_maintenance_window

  enable_performance_insights = var.db_enable_performance_insights
  performance_insights_retention = var.db_performance_insights_retention

  hnsw_m                = var.hnsw_m
  hnsw_ef_construction  = var.hnsw_ef_construction
  hnsw_ef_search        = var.hnsw_ef_search

  deletion_protection   = var.db_deletion_protection
}

# =============================================================================
# Module: ElastiCache Redis Cluster
# =============================================================================
module "elasticache" {
  source = "./modules/elasticache"

  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  private_subnet_ids    = module.vpc.private_subnet_ids
  security_group_ids    = [module.security_groups.elasticache_sg_id]

  engine_version        = var.redis_engine_version
  node_type             = var.redis_node_type
  num_node_groups       = var.redis_num_node_groups
  replicas_per_node_group = var.redis_replicas_per_node_group

  auth_token            = random_password.redis_password.result
  at_rest_encryption    = true
  transit_encryption    = true

  automatic_failover    = true
  multi_az              = true

  snapshot_retention_limit = var.redis_snapshot_retention
  snapshot_window       = var.redis_snapshot_window
  maintenance_window    = var.redis_maintenance_window
}

# =============================================================================
# Module: S3 Buckets
# =============================================================================
module "s3" {
  source = "./modules/s3"

  environment = var.environment

  buckets = {
    documents = {
      name        = "contextforge-${var.environment}-documents"
      versioning  = true
      encryption  = "AES256"
      lifecycle_rules = [
        {
          id      = "expire-old-versions"
          enabled = true
          noncurrent_version_expiration_days = 90
        }
      ]
      cors_rules = [
        {
          allowed_headers = ["*"]
          allowed_methods = ["GET", "PUT", "POST", "DELETE"]
          allowed_origins = var.cors_origins
          max_age         = 3600
        }
      ]
    }
    eval_datasets = {
      name        = "contextforge-${var.environment}-eval-datasets"
      versioning  = true
      encryption  = "AES256"
      lifecycle_rules = [
        {
          id      = "expire-old-versions"
          enabled = true
          noncurrent_version_expiration_days = 365
        }
      ]
    }
    model_artifacts = {
      name        = "contextforge-${var.environment}-model-artifacts"
      versioning  = true
      encryption  = "AES256"
      lifecycle_rules = [
        {
          id      = "expire-old-versions"
          enabled = true
          noncurrent_version_expiration_days = 365
        }
      ]
    }
    terraform_state = {
      name        = "contextforge-${var.environment}-terraform-state"
      versioning  = true
      encryption  = "AES256"
      lifecycle_rules = []
    }
  }
}

# =============================================================================
# Module: Secrets Manager
# =============================================================================
module "secrets" {
  source = "./modules/secrets"

  environment = var.environment

  secrets = {
    db_password = {
      name        = "contextforge/${var.environment}/database/password"
      description = "RDS PostgreSQL password"
      secret_string = random_password.db_password.result
      rotation_lambda_arn = var.db_rotation_lambda_arn
      rotation_rules = {
        automatically_after_days = 90
      }
    }
    redis_password = {
      name        = "contextforge/${var.environment}/redis/password"
      description = "ElastiCache Redis auth token"
      secret_string = random_password.redis_password.result
    }
    secret_key = {
      name        = "contextforge/${var.environment}/app/secret_key"
      description = "Application secret key for JWT/signing"
      secret_string = random_password.secret_key.result
    }
    openai_api_key = {
      name        = "contextforge/${var.environment}/openai/api_key"
      description = "OpenAI API key for embeddings"
      secret_string = var.openai_api_key
    }
    aws_credentials = {
      name        = "contextforge/${var.environment}/aws/credentials"
      description = "AWS credentials for Bedrock access"
      secret_string = jsonencode({
        access_key_id     = var.aws_access_key_id
        secret_access_key = var.aws_secret_access_key
        region            = var.aws_region
      })
    }
    mcp_cert = {
      name        = "contextforge/${var.environment}/mcp/cert"
      description = "MCP server TLS certificate"
      secret_string = var.mcp_cert
    }
    mcp_key = {
      name        = "contextforge/${var.environment}/mcp/key"
      description = "MCP server TLS private key"
      secret_string = var.mcp_key
    }
  }
}

# =============================================================================
# Module: IAM Roles
# =============================================================================
module "iam" {
  source = "./modules/iam"

  environment = var.environment
  account_id  = data.aws_caller_identity.current.account_id

  # ECS Task Role permissions
  ecs_task_permissions = [
    "secretsmanager:GetSecretValue",
    "secretsmanager:DescribeSecret",
    "ssm:GetParameters",
    "ssm:GetParameter",
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents",
    "logs:DescribeLogStreams",
    "logs:DescribeLogGroups",
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords",
    "xray:GetSamplingRules",
    "xray:GetSamplingTargets",
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:ListBucket"
  ]

  # CI/CD Deploy Role
  cicd_deploy_permissions = [
    "ecs:UpdateService",
    "ecs:RegisterTaskDefinition",
    "ecs:DescribeServices",
    "ecs:DescribeTaskDefinition",
    "ecs:ListTasks",
    "ecs:DescribeTasks",
    "ecs:RunTask",
    "ecs:StopTask",
    "ecr:GetAuthorizationToken",
    "ecr:BatchGetImage",
    "ecr:GetDownloadUrlForLayer",
    "ecr:PutImage",
    "ecr:InitiateLayerUpload",
    "ecr:UploadLayerPart",
    "ecr:CompleteLayerUpload",
    "iam:PassRole",
    "elasticloadbalancing:ModifyRule",
    "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:DescribeTargetHealth",
    "dynamodb:PutItem",
    "dynamodb:GetItem",
    "dynamodb:UpdateItem"
  ]

  # Terraform Role
  terraform_permissions = [
    "ec2:*",
    "ecs:*",
    "ecr:*",
    "elasticloadbalancing:*",
    "rds:*",
    "elasticache:*",
    "s3:*",
    "secretsmanager:*",
    "iam:*",
    "cloudwatch:*",
    "logs:*",
    "wafv2:*",
    "dynamodb:*",
    "kms:*",
    "ssm:*",
    "route53:*",
    "acm:*"
  ]
}

# =============================================================================
# Module: ECS Cluster & Services
# =============================================================================
module "ecs" {
  source = "./modules/ecs"

  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  private_subnet_ids    = module.vpc.private_subnet_ids
  security_group_ids    = [module.security_groups.ecs_sg_id]

  # Task Role
  task_role_arn         = module.iam.ecs_task_role_arn
  execution_role_arn    = module.iam.ecs_execution_role_arn

  # Service configurations
  api_service = {
    name            = "contextforge-api"
    cpu             = var.api_cpu
    memory          = var.api_memory
    desired_count   = var.api_desired_count
    max_capacity    = var.api_max_capacity
    min_capacity    = var.api_min_capacity
    container_port  = 8000
    health_check_path = "/health"
    environment_variables = {
      APP_ENV                 = var.environment
      VECTOR_STORE            = "pgvector"
      OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
      OTEL_SERVICE_NAME       = "contextforge-api"
      LOG_LEVEL               = "INFO"
      LOG_FORMAT              = "json"
    }
    secrets = [
      { name = "DATABASE_URL", valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:contextforge/${var.environment}/database/url" },
      { name = "REDIS_URL", valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:contextforge/${var.environment}/redis/url" },
      { name = "SECRET_KEY", valueFrom = module.secrets.secret_arns["secret_key"] },
      { name = "OPENAI_API_KEY", valueFrom = module.secrets.secret_arns["openai_api_key"] },
      { name = "AWS_CREDENTIALS", valueFrom = module.secrets.secret_arns["aws_credentials"] }
    ]
  }

  mcp_service = {
    name            = "contextforge-mcp"
    cpu             = var.mcp_cpu
    memory          = var.mcp_memory
    desired_count   = var.mcp_desired_count
    max_capacity    = var.mcp_max_capacity
    min_capacity    = var.mcp_min_capacity
    container_port  = 8001
    health_check_path = "/health"
    environment_variables = {
      APP_ENV                 = var.environment
      VECTOR_STORE            = "pgvector"
      OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
      OTEL_SERVICE_NAME       = "contextforge-mcp"
      LOG_LEVEL               = "INFO"
      LOG_FORMAT              = "json"
      MCP_AUTH_ENABLED        = "true"
    }
    secrets = [
      { name = "DATABASE_URL", valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:contextforge/${var.environment}/database/url" },
      { name = "REDIS_URL", valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:contextforge/${var.environment}/redis/url" },
      { name = "MCP_CERT", valueFrom = module.secrets.secret_arns["mcp_cert"] },
      { name = "MCP_KEY", valueFrom = module.secrets.secret_arns["mcp_key"] },
      { name = "AWS_CREDENTIALS", valueFrom = module.secrets.secret_arns["aws_credentials"] }
    ]
  }

  worker_service = {
    name            = "contextforge-worker"
    cpu             = var.worker_cpu
    memory          = var.worker_memory
    desired_count   = var.worker_desired_count
    max_capacity    = var.worker_max_capacity
    min_capacity    = var.worker_min_capacity
    container_port  = 0  # No port mapping for worker
    health_check_path = ""  # Custom health check
    environment_variables = {
      APP_ENV                 = var.environment
      VECTOR_STORE            = "pgvector"
      OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
      OTEL_SERVICE_NAME       = "contextforge-worker"
      LOG_LEVEL               = "INFO"
      LOG_FORMAT              = "json"
      CELERY_WORKER_CONCURRENCY = "4"
    }
    secrets = [
      { name = "DATABASE_URL", valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:contextforge/${var.environment}/database/url" },
      { name = "REDIS_URL", valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:contextforge/${var.environment}/redis/url" },
      { name = "OPENAI_API_KEY", valueFrom = module.secrets.secret_arns["openai_api_key"] },
      { name = "AWS_CREDENTIALS", valueFrom = module.secrets.secret_arns["aws_credentials"] }
    ]
  }

  # ECR Repositories
  ecr_repositories = {
    api = "contextforge-${var.environment}-api"
    mcp = "contextforge-${var.environment}-mcp"
    worker = "contextforge-${var.environment}-worker"
  }
}

# =============================================================================
# Module: ALB with WAF
# =============================================================================
module "alb" {
  source = "./modules/alb"

  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  public_subnet_ids     = module.vpc.public_subnet_ids
  security_group_ids    = [module.security_groups.alb_sg_id]

  # Target Groups
  api_target_group_arns = {
    blue = module.ecs.api_blue_target_group_arn
    green = module.ecs.api_green_target_group_arn
  }
  mcp_target_group_arns = {
    blue = module.ecs.mcp_blue_target_group_arn
    green = module.ecs.mcp_green_target_group_arn
  }

  # WAF
  waf_enabled           = var.waf_enabled
  waf_rate_limit        = var.waf_rate_limit
  waf_ip_allowlist      = var.mcp_allowed_ips
  waf_geo_block_countries = var.waf_geo_block_countries
  waf_web_acl_arn       = module.waf.web_acl_arn
  resource_arn          = aws_lb.main.arn

  # SSL
  ssl_certificate_arn   = var.ssl_certificate_arn

  # Access logs
  access_logs_bucket    = module.s3.bucket_names["documents"]

  # Route53 for certificate validation
  route53_zone_id       = var.route53_zone_id

  # Health checks
  health_check_path     = "/health"
  healthy_threshold     = 2
  unhealthy_threshold   = 3
  timeout               = 10
  interval              = 30
}

# =============================================================================
# Module: CloudWatch Monitoring
# =============================================================================
module "cloudwatch" {
  source = "./modules/cloudwatch"

  environment = var.environment

  # Log groups
  log_groups = {
    api = "/ecs/contextforge-${var.environment}/api"
    mcp = "/ecs/contextforge-${var.environment}/mcp"
    worker = "/ecs/contextforge-${var.environment}/worker"
    beat = "/ecs/contextforge-${var.environment}/beat"
    otel = "/ecs/contextforge-${var.environment}/otel"
  }

  # Alarms
  alarms = {
    api_high_latency = {
      name          = "contextforge-${var.environment}-api-high-latency"
      description   = "API p99 latency > 2s"
      metric_name   = "TargetResponseTime"
      namespace     = "AWS/ApplicationELB"
      statistic     = "p99"
      period        = 60
      evaluation_periods = 3
      threshold     = 2000
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        TargetGroup = module.ecs.api_target_group_name
        LoadBalancer = module.alb.load_balancer_name
      }
    }
    api_high_error_rate = {
      name          = "contextforge-${var.environment}-api-high-error-rate"
      description   = "API 5xx error rate > 1%"
      metric_name   = "HTTPCode_Target_5XX_Count"
      namespace     = "AWS/ApplicationELB"
      statistic     = "Sum"
      period        = 60
      evaluation_periods = 3
      threshold     = 10
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        TargetGroup = module.ecs.api_target_group_name
        LoadBalancer = module.alb.load_balancer_name
      }
    }
    worker_queue_depth = {
      name          = "contextforge-${var.environment}-worker-queue-depth"
      description   = "Celery queue depth > 1000"
      metric_name   = "ApproximateNumberOfMessagesVisible"
      namespace     = "AWS/SQS"
      statistic     = "Average"
      period        = 300
      evaluation_periods = 2
      threshold     = 1000
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        QueueName = "contextforge-${var.environment}-celery"
      }
    }
    db_cpu_high = {
      name          = "contextforge-${var.environment}-db-cpu-high"
      description   = "RDS CPU > 80%"
      metric_name   = "CPUUtilization"
      namespace     = "AWS/RDS"
      statistic     = "Average"
      period        = 300
      evaluation_periods = 3
      threshold     = 80
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        DBInstanceIdentifier = module.rds.db_instance_identifier
      }
    }
    redis_memory_high = {
      name          = "contextforge-${var.environment}-redis-memory-high"
      description   = "ElastiCache memory > 85%"
      metric_name   = "DatabaseMemoryUsagePercentage"
      namespace     = "AWS/ElastiCache"
      statistic     = "Average"
      period        = 300
      evaluation_periods = 3
      threshold     = 85
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        CacheClusterId = module.elasticache.cache_cluster_id
      }
    }
    ecs_service_cpu_high = {
      name          = "contextforge-${var.environment}-ecs-service-cpu-high"
      description   = "ECS service CPU > 80%"
      metric_name   = "CPUUtilization"
      namespace     = "AWS/ECS"
      statistic     = "Average"
      period        = 300
      evaluation_periods = 3
      threshold     = 80
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        ClusterName = module.ecs.cluster_name
        ServiceName = "contextforge-${var.environment}-api"
      }
    }
  }

  # Cost monitoring
  cost_alarms = {
    estimated_charges = {
      name          = "contextforge-${var.environment}-estimated-charges"
      description   = "Estimated monthly charges > $5000"
      metric_name   = "EstimatedCharges"
      namespace     = "AWS/Billing"
      statistic     = "Maximum"
      period        = 21600
      evaluation_periods = 1
      threshold     = 5000
      comparison_operator = "GreaterThanThreshold"
      dimensions = {
        Currency = "USD"
      }
    }
  }
}

# =============================================================================
# Module: WAF
# =============================================================================
module "waf" {
  source = "./modules/waf"

  environment = var.environment

  # Rate limiting
  rate_limit_rules = [
    {
      name        = "api-rate-limit"
      priority    = 1
      limit       = var.waf_rate_limit
      window_sec  = 300
      scope_down_statement = {
        byte_match_statement = {
          field_to_match = { single_header = { name = "host" } }
          positional_constraint = "CONTAINS"
          search_string = "api"
          text_transformations = [{ priority = 0, type = "NONE" }]
        }
      }
    },
    {
      name        = "mcp-rate-limit"
      priority    = 2
      limit       = 100
      window_sec  = 60
      scope_down_statement = {
        byte_match_statement = {
          field_to_match = { single_header = { name = "host" } }
          positional_constraint = "CONTAINS"
          search_string = "mcp"
          text_transformations = [{ priority = 0, type = "NONE" }]
        }
      }
    }
  ]

  # IP Allowlist for MCP
  ip_allowlist = var.mcp_allowed_ips

  # Geo blocking
  geo_block_countries = var.waf_geo_block_countries

  # Managed rules
  managed_rule_groups = [
    "AWSManagedRulesCommonRuleSet",
    "AWSManagedRulesKnownBadInputsRuleSet",
    "AWSManagedRulesSQLiRuleSet",
    "AWSManagedRulesLinuxRuleSet",
    "AWSManagedRulesAnonymousIpList"
  ]

  # Logging destination
  logging_destination_arn = module.s3.bucket_arns["documents"]

  # Associate with ALB
  resource_arn = module.alb.load_balancer_arn
}

# =============================================================================
# Outputs
# =============================================================================
output "alb_dns_name" {
  description = "ALB DNS name"
  value       = module.alb.load_balancer_dns_name
}

output "alb_arn" {
  description = "ALB ARN"
  value       = module.alb.load_balancer_arn
}

output "api_target_group_blue_arn" {
  description = "API Blue target group ARN"
  value       = module.ecs.api_blue_target_group_arn
}

output "api_target_group_green_arn" {
  description = "API Green target group ARN"
  value       = module.ecs.api_green_target_group_arn
}

output "mcp_target_group_blue_arn" {
  description = "MCP Blue target group ARN"
  value       = module.ecs.mcp_blue_target_group_arn
}

output "mcp_target_group_green_arn" {
  description = "MCP Green target group ARN"
  value       = module.ecs.mcp_green_target_group_arn
}

output "db_endpoint" {
  description = "RDS endpoint"
  value       = module.rds.db_endpoint
  sensitive   = true
}

output "db_port" {
  description = "RDS port"
  value       = module.rds.db_port
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint"
  value       = module.elasticache.redis_endpoint
  sensitive   = true
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = module.elasticache.redis_port
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

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = module.ecs.cluster_arn
}

output "task_role_arn" {
  description = "ECS task role ARN"
  value       = module.iam.ecs_task_role_arn
}

output "execution_role_arn" {
  description = "ECS execution role ARN"
  value       = module.iam.ecs_execution_role_arn
}

output "cicd_deploy_role_arn" {
  description = "CI/CD deploy role ARN"
  value       = module.iam.cicd_deploy_role_arn
}

output "terraform_state_bucket" {
  description = "Terraform state bucket"
  value       = module.s3.bucket_names["terraform_state"]
}

output "terraform_locks_table" {
  description = "Terraform locks DynamoDB table"
  value       = module.s3.locks_table_name
}