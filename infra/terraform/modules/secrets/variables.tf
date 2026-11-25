# Secrets Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "secrets" {
  description = "Map of secret configurations"
  type = map(object({
    name        = string
    description = string
    secret_string = string
    rotation_lambda_arn = optional(string)
    rotation_rules = optional(object({
      automatically_after_days = number
    }))
  }))
}