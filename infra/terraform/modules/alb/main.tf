# ALB Module for ContextForge

# =============================================================================
# Security Group for ALB (created in security_groups module, passed in)
# =============================================================================

# =============================================================================
# Application Load Balancer
# =============================================================================
resource "aws_lb" "main" {
  name               = "contextforge-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = var.security_group_ids
  subnets            = var.public_subnet_ids
  enable_deletion_protection = var.environment == "prod"

  access_logs {
    bucket  = var.access_logs_bucket
    prefix  = "contextforge/${var.environment}/alb"
    enabled = true
  }

  tags = {
    Name = "contextforge-${var.environment}-alb"
  }
}

# =============================================================================
# HTTP Listener (redirect to HTTPS)
# =============================================================================
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# =============================================================================
# HTTPS Listener
# =============================================================================
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.ssl_certificate_arn != "" ? var.ssl_certificate_arn : aws_acm_certificate.main.arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\": \"Not found\"}"
      status_code  = "404"
    }
  }
}

# =============================================================================
# ACM Certificate (if not provided)
# =============================================================================
resource "aws_acm_certificate" "main" {
  count = var.ssl_certificate_arn == "" ? 1 : 0

  domain_name       = "*.contextforge-${var.environment}.dev"
  validation_method = "DNS"

  subject_alternative_names = [
    "contextforge-${var.environment}.dev",
    "api.contextforge-${var.environment}.dev",
    "mcp.contextforge-${var.environment}.dev"
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "main" {
  count = var.ssl_certificate_arn == "" ? 1 : 0

  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

resource "aws_route53_record" "cert_validation" {
  count = var.ssl_certificate_arn == "" ? length(aws_acm_certificate.main[0].domain_validation_options) : 0

  zone_id = var.route53_zone_id
  name    = aws_acm_certificate.main[0].domain_validation_options[count.index].resource_record_name
  type    = aws_acm_certificate.main[0].domain_validation_options[count.index].resource_record_type
  records = [aws_acm_certificate.main[0].domain_validation_options[count.index].resource_record_value]
  ttl     = 60
}

# =============================================================================
# API Target Group Rules (Blue/Green)
# =============================================================================
resource "aws_lb_listener_rule" "api_blue" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = var.api_target_group_arns.blue
  }

  condition {
    host_header {
      values = ["api.contextforge-${var.environment}.dev", "api.contextforge-${var.environment}.com"]
    }
  }
}

resource "aws_lb_listener_rule" "api_green" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 101

  action {
    type             = "forward"
    target_group_arn = var.api_target_group_arns.green
  }

  condition {
    host_header {
      values = ["api-green.contextforge-${var.environment}.dev"]
    }
  }
}

# =============================================================================
# MCP Target Group Rules (Blue/Green)
# =============================================================================
resource "aws_lb_listener_rule" "mcp_blue" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 200

  action {
    type             = "forward"
    target_group_arn = var.mcp_target_group_arns.blue
  }

  condition {
    host_header {
      values = ["mcp.contextforge-${var.environment}.dev", "mcp.contextforge-${var.environment}.com"]
    }
  }
}

resource "aws_lb_listener_rule" "mcp_green" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 201

  action {
    type             = "forward"
    target_group_arn = var.mcp_target_group_arns.green
  }

  condition {
    host_header {
      values = ["mcp-green.contextforge-${var.environment}.dev"]
    }
  }
}

# =============================================================================
# Health Check Path Rule (for ALB health checks)
# =============================================================================
resource "aws_lb_listener_rule" "health_check" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 999

  action {
    type             = "forward"
    target_group_arn = var.api_target_group_arns.blue
  }

  condition {
    path_pattern {
      values = [var.health_check_path]
    }
  }
}

# =============================================================================
# WAF Association
# =============================================================================
resource "aws_wafv2_web_acl_association" "main" {
  count  = var.waf_enabled ? 1 : 0
  resource_arn = var.resource_arn
  web_acl_arn  = var.waf_web_acl_arn
}

# =============================================================================
# Outputs
# =============================================================================
output "load_balancer_arn" {
  description = "ALB ARN"
  value       = aws_lb.main.arn
}

output "load_balancer_dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.main.dns_name
}

output "load_balancer_name" {
  description = "ALB name"
  value       = aws_lb.main.name
}

output "load_balancer_zone_id" {
  description = "ALB zone ID"
  value       = aws_lb.main.zone_id
}

output "https_listener_arn" {
  description = "HTTPS listener ARN"
  value       = aws_lb_listener.https.arn
}

output "api_blue_listener_rule_arn" {
  description = "API Blue listener rule ARN"
  value       = aws_lb_listener_rule.api_blue.arn
}

output "api_green_listener_rule_arn" {
  description = "API Green listener rule ARN"
  value       = aws_lb_listener_rule.api_green.arn
}

output "mcp_blue_listener_rule_arn" {
  description = "MCP Blue listener rule ARN"
  value       = aws_lb_listener_rule.mcp_blue.arn
}

output "mcp_green_listener_rule_arn" {
  description = "MCP Green listener rule ARN"
  value       = aws_lb_listener_rule.mcp_green.arn
}