# S3 Buckets Module for ContextForge

# =============================================================================
# KMS Key for S3 Encryption
# =============================================================================
resource "aws_kms_key" "s3" {
  description             = "KMS key for S3 bucket encryption"
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
        Sid    = "Allow S3 to use the key"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
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
    Name = "contextforge-${var.environment}-s3-key"
  }
}

resource "aws_kms_alias" "s3" {
  name          = "alias/contextforge-${var.environment}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

# =============================================================================
# S3 Buckets
# =============================================================================
resource "aws_s3_bucket" "buckets" {
  for_each = var.buckets

  bucket = each.value.name

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm     = each.value.encryption == "AES256" ? "AES256" : "aws:kms"
        kms_master_key_id = each.value.encryption == "AES256" ? null : aws_kms_key.s3.arn
      }
      bucket_key_enabled = true
    }
  }

  versioning {
    enabled = each.value.versioning
  }

  lifecycle_rule {
    for_each = { for rule in each.value.lifecycle_rules : rule.id => rule }
    id      = each.value.id
    enabled = each.value.enabled

    dynamic "noncurrent_version_expiration" {
      for_each = each.value.noncurrent_version_expiration_days != null ? [each.value] : []
      content {
        noncurrent_days = each.value.noncurrent_version_expiration_days
      }
    }

    dynamic "expiration" {
      for_each = each.value.expiration_days != null ? [each.value] : []
      content {
        days = each.value.expiration_days
      }
    }
  }

  dynamic "cors_rule" {
    for_each = each.value.cors_rules != null ? each.value.cors_rules : []
    content {
      allowed_headers = cors_rule.value.allowed_headers
      allowed_methods = cors_rule.value.allowed_methods
      allowed_origins = cors_rule.value.allowed_origins
      max_age         = cors_rule.value.max_age
    }
  }

  tags = {
    Name = each.value.name
    Environment = var.environment
  }
}

# =============================================================================
# S3 Bucket Public Access Block
# =============================================================================
resource "aws_s3_bucket_public_access_block" "buckets" {
  for_each = var.buckets

  bucket = aws_s3_bucket.buckets[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =============================================================================
# S3 Bucket Policy (for documents bucket - allow CloudFront/CDN access)
# =============================================================================
resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.buckets["documents"].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontAccess"
        Effect = "Allow"
        Principal = {
          CanonicalUser = var.cloudfront_oai_id != "" ? var.cloudfront_oai_id : "*"
        }
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.buckets["documents"].arn,
          "${aws_s3_bucket.buckets["documents"].arn}/*"
        ]
        Condition = {
          StringEquals = {
            "aws:SourceArn" = var.cloudfront_distribution_arn != "" ? var.cloudfront_distribution_arn : "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"
          }
        }
      }
    ]
  })
}

# =============================================================================
# DynamoDB Table for Terraform State Locking
# =============================================================================
resource "aws_dynamodb_table" "terraform_locks" {
  name         = "contextforge-${var.environment}-terraform-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  ttl {
    attribute_name = "TTL"
    enabled        = true
  }

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.s3.arn
  }

  tags = {
    Name = "contextforge-${var.environment}-terraform-locks"
  }
}

# =============================================================================
# Outputs
# =============================================================================
output "bucket_names" {
  description = "Map of bucket names"
  value       = { for k, v in aws_s3_bucket.buckets : k => v.id }
}

output "bucket_arns" {
  description = "Map of bucket ARNs"
  value       = { for k, v in aws_s3_bucket.buckets : k => v.arn }
}

output "locks_table_name" {
  description = "DynamoDB table name for Terraform locks"
  value       = aws_dynamodb_table.terraform_locks.name
}

output "kms_key_arn" {
  description = "KMS key ARN"
  value       = aws_kms_key.s3.arn
}