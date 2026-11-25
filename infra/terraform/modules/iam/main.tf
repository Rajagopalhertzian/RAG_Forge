# IAM Roles Module for ContextForge

# =============================================================================
# ECS Task Role (for application permissions)
# =============================================================================
resource "aws_iam_role" "ecs_task" {
  name = "contextforge-${var.environment}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "contextforge-${var.environment}-ecs-task-role"
  }
}

resource "aws_iam_policy" "ecs_task" {
  name = "contextforge-${var.environment}-ecs-task-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = var.ecs_task_permissions
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_task.arn
}

# =============================================================================
# ECS Execution Role (for pulling images, CloudWatch logs)
# =============================================================================
resource "aws_iam_role" "ecs_execution" {
  name = "contextforge-${var.environment}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "contextforge-${var.environment}-ecs-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Additional permissions for execution role
resource "aws_iam_policy" "ecs_execution_extra" {
  name = "contextforge-${var.environment}-ecs-execution-extra-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
          "ssm:GetParameters",
          "ssm:GetParameter",
          "kms:Decrypt"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_extra" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_extra.arn
}

# =============================================================================
# CI/CD Deploy Role (for GitHub Actions)
# =============================================================================
resource "aws_iam_role" "cicd_deploy" {
  name = "contextforge-${var.environment}-cicd-deploy-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })

  tags = {
    Name = "contextforge-${var.environment}-cicd-deploy-role"
  }
}

resource "aws_iam_policy" "cicd_deploy" {
  name = "contextforge-${var.environment}-cicd-deploy-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = var.cicd_deploy_permissions
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cicd_deploy" {
  role       = aws_iam_role.cicd_deploy.name
  policy_arn = aws_iam_policy.cicd_deploy.arn
}

# =============================================================================
# Terraform Role (for CI/CD Terraform operations)
# =============================================================================
resource "aws_iam_role" "terraform" {
  name = "contextforge-${var.environment}-terraform-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })

  tags = {
    Name = "contextforge-${var.environment}-terraform-role"
  }
}

resource "aws_iam_policy" "terraform" {
  name = "contextforge-${var.environment}-terraform-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = var.terraform_permissions
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "terraform" {
  role       = aws_iam_role.terraform.name
  policy_arn = aws_iam_policy.terraform.arn
}

# =============================================================================
# Evaluation Role (for nightly evaluation jobs)
# =============================================================================
resource "aws_iam_role" "eval" {
  name = "contextforge-${var.environment}-eval-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })

  tags = {
    Name = "contextforge-${var.environment}-eval-role"
  }
}

resource "aws_iam_policy" "eval" {
  name = "contextforge-${var.environment}-eval-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances",
          "rds:DescribeDBClusters",
          "elasticache:DescribeReplicationGroups",
          "ecs:DescribeServices",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
          "secretsmanager:GetSecretValue",
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "eval" {
  role       = aws_iam_role.eval.name
  policy_arn = aws_iam_policy.eval.arn
}

# =============================================================================
# Service-Linked Roles (created automatically but good to declare)
# =============================================================================
resource "aws_iam_service_linked_role" "ecs" {
  aws_service_name = "ecs.amazonaws.com"
}

resource "aws_iam_service_linked_role" "rds" {
  aws_service_name = "rds.amazonaws.com"
}

resource "aws_iam_service_linked_role" "elasticache" {
  aws_service_name = "elasticache.amazonaws.com"
}

resource "aws_iam_service_linked_role" "elasticloadbalancing" {
  aws_service_name = "elasticloadbalancing.amazonaws.com"
}

# =============================================================================
# Outputs
# =============================================================================
output "ecs_task_role_arn" {
  description = "ECS task role ARN"
  value       = aws_iam_role.ecs_task.arn
}

output "ecs_task_role_name" {
  description = "ECS task role name"
  value       = aws_iam_role.ecs_task.name
}

output "ecs_execution_role_arn" {
  description = "ECS execution role ARN"
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_execution_role_name" {
  description = "ECS execution role name"
  value       = aws_iam_role.ecs_execution.name
}

output "cicd_deploy_role_arn" {
  description = "CI/CD deploy role ARN"
  value       = aws_iam_role.cicd_deploy.arn
}

output "terraform_role_arn" {
  description = "Terraform role ARN"
  value       = aws_iam_role.terraform.arn
}

output "eval_role_arn" {
  description = "Evaluation role ARN"
  value       = aws_iam_role.eval.arn
}