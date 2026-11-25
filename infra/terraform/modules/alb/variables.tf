# ALB Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs"
  type        = list(string)
}

variable "api_target_group_arns" {
  description = "API target group ARNs (blue/green)"
  type = object({
    blue  = string
    green = string
  })
}

variable "mcp_target_group_arns" {
  description = "MCP target group ARNs (blue/green)"
  type = object({
    blue  = string
    green = string
  })
}

variable "waf_enabled" {
  description = "Enable WAF"
  type        = bool
}

variable "waf_web_acl_arn" {
  description = "WAF Web ACL ARN"
  type        = string
  default     = ""
}

variable "resource_arn" {
  description = "Resource ARN to associate WAF with"
  type        = string
}

variable "ssl_certificate_arn" {
  description = "ACM SSL certificate ARN"
  type        = string
  default     = ""
}

variable "access_logs_bucket" {
  description = "S3 bucket for ALB access logs"
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 zone ID for certificate validation"
  type        = string
  default     = ""
}

variable "health_check_path" {
  description = "Health check path"
  type        = string
  default     = "/health"
}

variable "healthy_threshold" {
  description = "Healthy threshold"
  type        = number
  default     = 2
}

variable "unhealthy_threshold" {
  description = "Unhealthy threshold"
  type        = number
  default     = 3
}

variable "timeout" {
  description = "Health check timeout"
  type        = number
  default     = 10
}

variable "interval" {
  description = "Health check interval"
  type        = number
  default     = 30
}