# WAF Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "rate_limit_rules" {
  description = "Rate limiting rules"
  type = list(object({
    name                 = string
    priority             = number
    limit                = number
    window_sec           = number
    scope_down_statement = optional(object({
      byte_match_statement = object({
        field_to_match = object({
          single_header = object({
            name = string
          })
        })
        positional_constraint = string
        search_string         = string
        text_transformations = list(object({
          priority = number
          type     = string
        }))
      })
    }))
  }))
  default = []
}

variable "ip_allowlist" {
  description = "IP addresses to allowlist for MCP"
  type        = list(string)
  default     = []
}

variable "geo_block_countries" {
  description = "Countries to block (ISO 3166-1 alpha-2)"
  type        = list(string)
  default     = []
}

variable "managed_rule_groups" {
  description = "AWS Managed Rule Groups to enable"
  type        = list(string)
  default     = [
    "AWSManagedRulesKnownBadInputsRuleSet",
    "AWSManagedRulesSQLiRuleSet",
    "AWSManagedRulesLinuxRuleSet",
    "AWSManagedRulesAnonymousIpList"
  ]
}

variable "logging_destination_arn" {
  description = "ARN of the logging destination (S3, CloudWatch, etc.)"
  type        = string
  default     = ""
}