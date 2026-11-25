# S3 Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "buckets" {
  description = "Map of bucket configurations"
  type = map(object({
    name        = string
    versioning  = bool
    encryption  = string
    lifecycle_rules = list(object({
      id      = string
      enabled = bool
      noncurrent_version_expiration_days = optional(number)
      expiration_days = optional(number)
    }))
    cors_rules = optional(list(object({
      allowed_headers = list(string)
      allowed_methods = list(string)
      allowed_origins = list(string)
      max_age         = number
    })))
  }))
}

variable "cloudfront_oai_id" {
  description = "CloudFront Origin Access Identity ID"
  type        = string
  default     = ""
}

variable "cloudfront_distribution_arn" {
  description = "CloudFront Distribution ARN"
  type        = string
  default     = ""
}