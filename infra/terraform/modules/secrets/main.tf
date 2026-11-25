# Secrets Manager Module for ContextForge

# =============================================================================
# KMS Key for Secrets Encryption
# =============================================================================
resource "aws_kms_key" "secrets" {
  description             = "KMS key for Secrets Manager encryption"
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
        Sid    = "Allow Secrets Manager to use the key"
        Effect = "Allow"
        Principal = {
          Service = "secretsmanager.amazonaws.com"
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
    Name = "contextforge-${var.environment}-secrets-key"
  }
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/contextforge-${var.environment}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# =============================================================================
# Secrets
# =============================================================================
resource "aws_secretsmanager_secret" "secrets" {
  for_each = var.secrets

  name                    = each.value.name
  description             = each.value.description
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 30

  tags = {
    Name = each.value.name
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "secrets" {
  for_each = var.secrets

  secret_id = aws_secretsmanager_secret.secrets[each.key].id
  secret_string = each.value.secret_string
}

# =============================================================================
# Secret Rotation (for database password)
# =============================================================================
resource "aws_secretsmanager_secret_rotation" "db_password" {
  count = var.secrets["db_password"] != null && var.secrets["db_password"].rotation_lambda_arn != "" ? 1 : 0

  secret_id           = aws_secretsmanager_secret.secrets["db_password"].id
  rotation_lambda_arn = var.secrets["db_password"].rotation_lambda_arn
  rotation_rules {
    automatically_after_days = var.secrets["db_password"].rotation_rules.automatically_after_days
  }
}

# =============================================================================
# Outputs
# =============================================================================
output "secret_arns" {
  description = "Map of secret ARNs"
  value       = { for k, v in aws_secretsmanager_secret.secrets : k => v.arn }
}

output "secret_names" {
  description = "Map of secret names"
  value       = { for k, v in aws_secretsmanager_secret.secrets : k => v.name }
}

output "kms_key_arn" {
  description = "KMS key ARN"
  value       = aws_kms_key.secrets.arn
}