# Security Groups Module Variables

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to access ALB"
  type        = list(string)
}

variable "mcp_allowed_ips" {
  description = "IP addresses allowed to access MCP gateway"
  type        = list(string)
  default     = []
}

variable "bastion_ingress_cidrs" {
  description = "CIDR blocks allowed for bastion/SSH access"
  type        = list(string)
  default     = []
}