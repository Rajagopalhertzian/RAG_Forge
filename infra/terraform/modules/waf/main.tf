# WAFv2 Module for ContextForge

# =============================================================================
# IP Set for MCP Allowlist
# =============================================================================
resource "aws_wafv2_ip_set" "mcp_allowlist" {
  count  = length(var.ip_allowlist) > 0 ? 1 : 0
  name   = "contextforge-${var.environment}-mcp-allowlist"
  scope  = "REGIONAL"
  ip_address_version = "IPV4"
  addresses = var.ip_allowlist

  tags = {
    Name = "contextforge-${var.environment}-mcp-allowlist"
  }
}

# =============================================================================
# Geo Match Rule for Country Blocking
# =============================================================================
resource "aws_wafv2_web_acl" "main" {
  name  = "contextforge-${var.environment}-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # Rate limiting rules
  dynamic "rule" {
    for_each = var.rate_limit_rules
    content {
      name     = rule.value.name
      priority = rule.value.priority

      action {
        block {}
      }

      statement {
        rate_based_statement {
          limit              = rule.value.limit
          aggregate_key_type = "IP"
          scope_down_statement {
            dynamic "byte_match_statement" {
              for_each = rule.value.scope_down_statement != null ? [rule.value.scope_down_statement] : []
              content {
                field_to_match {
                  single_header = byte_match_statement.value.field_to_match.single_header
                }
                positional_constraint = byte_match_statement.value.positional_constraint
                search_string         = byte_match_statement.value.search_string
                text_transformation {
                  priority = byte_match_statement.value.text_transformations[0].priority
                  type     = byte_match_statement.value.text_transformations[0].type
                }
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.value.name
        sampled_requests_enabled   = true
      }
    }
  }

  # IP Allowlist for MCP
  rule {
    name     = "mcp-ip-allowlist"
    priority = 10

    action {
      allow {}
    }

    statement {
      ip_set_reference_statement {
        arn = length(var.ip_allowlist) > 0 ? aws_wafv2_ip_set.mcp_allowlist[0].arn : ""
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "MCPAllowlist"
      sampled_requests_enabled   = true
    }
  }

  # Geo Blocking
  dynamic "rule" {
    for_each = var.geo_block_countries
    content {
      name     = "geo-block-${rule.value}"
      priority = 20 + index(var.geo_block_countries, rule.value)

      action {
        block {}
      }

      statement {
        geo_match_statement {
          country_codes = [rule.value]
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "GeoBlock${upper(rule.value)}"
        sampled_requests_enabled   = true
      }
    }
  }

  # Managed Rule Groups
  dynamic "rule" {
    for_each = var.managed_rule_groups
    content {
      name     = "managed-${rule.value}"
      priority = 100 + index(var.managed_rule_groups, rule.value)

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          name        = rule.value
          vendor_name = "AWS"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "Managed${replace(rule.value, "AWSManagedRules", "")}"
        sampled_requests_enabled   = true
      }
    }
  }

  # Core Rule Set (always enabled)
  rule {
    name     = "managed-core-rule-set"
    priority = 100

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ManagedCoreRuleSet"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "ContextForgeWAF"
    sampled_requests_enabled   = true
  }

  tags = {
    Name = "contextforge-${var.environment}-waf"
  }
}

# =============================================================================
# Logging Configuration
# =============================================================================
resource "aws_wafv2_web_acl_logging_configuration" "main" {
  resource_arn = aws_wafv2_web_acl.main.arn
  log_destination_configs = [var.logging_destination_arn]

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }

  redacted_fields {
    single_header {
      name = "cookie"
    }
  }

  redacted_fields {
    single_header {
      name = "x-api-key"
    }
  }
}

# =============================================================================
# Outputs
# =============================================================================
output "web_acl_arn" {
  description = "WAF Web ACL ARN"
  value       = aws_wafv2_web_acl.main.arn
}

output "web_acl_id" {
  description = "WAF Web ACL ID"
  value       = aws_wafv2_web_acl.main.id
}

output "ip_set_arn" {
  description = "IP Set ARN for MCP allowlist"
  value       = length(aws_wafv2_ip_set.mcp_allowlist) > 0 ? aws_wafv2_ip_set.mcp_allowlist[0].arn : null
}