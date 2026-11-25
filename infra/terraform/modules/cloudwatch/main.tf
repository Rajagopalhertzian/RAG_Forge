# CloudWatch Monitoring Module for ContextForge

# =============================================================================
# Log Groups
# =============================================================================
resource "aws_cloudwatch_log_group" "log_groups" {
  for_each = var.log_groups

  name              = each.value
  retention_in_days = 30
  kms_key_id        = var.kms_key_id != "" ? var.kms_key_id : null

  tags = {
    Name = each.value
    Environment = var.environment
  }
}

# =============================================================================
# Metric Filters for Logs
# =============================================================================
resource "aws_cloudwatch_log_metric_filter" "api_errors" {
  name           = "contextforge-${var.environment}-api-errors"
  log_group_name = "/ecs/contextforge-${var.environment}/api"
  pattern        = "[timestamp, level=ERROR, ...]"

  metric_transformation {
    name      = "APIErrors"
    namespace = "ContextForge/Application"
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "api_warnings" {
  name           = "contextforge-${var.environment}-api-warnings"
  log_group_name = "/ecs/contextforge-${var.environment}/api"
  pattern        = "[timestamp, level=WARNING, ...]"

  metric_transformation {
    name      = "APIWarnings"
    namespace = "ContextForge/Application"
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_errors" {
  name           = "contextforge-${var.environment}-worker-errors"
  log_group_name = "/ecs/contextforge-${var.environment}/worker"
  pattern        = "[timestamp, level=ERROR, ...]"

  metric_transformation {
    name      = "WorkerErrors"
    namespace = "ContextForge/Application"
    value     = "1"
  }
}

# =============================================================================
# CloudWatch Alarms
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "alarms" {
  for_each = var.alarms

  alarm_name          = each.value.name
  alarm_description   = each.value.description
  comparison_operator = each.value.comparison_operator
  evaluation_periods  = each.value.evaluation_periods
  metric_name         = each.value.metric_name
  namespace           = each.value.namespace
  period              = each.value.period
  statistic           = each.value.statistic
  threshold           = each.value.threshold

  dimensions = each.value.dimensions

  alarm_actions = var.alarm_actions
  ok_actions    = var.ok_actions

  tags = {
    Name = each.value.name
    Environment = var.environment
  }
}

# =============================================================================
# Cost Monitoring Alarms
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "cost_alarms" {
  for_each = var.cost_alarms

  alarm_name          = each.value.name
  alarm_description   = each.value.description
  comparison_operator = each.value.comparison_operator
  evaluation_periods  = each.value.evaluation_periods
  metric_name         = each.value.metric_name
  namespace           = each.value.namespace
  period              = each.value.period
  statistic           = each.value.statistic
  threshold           = each.value.threshold

  dimensions = each.value.dimensions

  alarm_actions = var.alarm_actions
  ok_actions    = var.ok_actions

  tags = {
    Name = each.value.name
    Environment = var.environment
  }
}

# =============================================================================
# Composite Alarms (for critical alerts)
# =============================================================================
resource "aws_cloudwatch_composite_alarm" "critical" {
  alarm_name        = "contextforge-${var.environment}-critical"
  alarm_description = "Critical composite alarm for ContextForge ${var.environment}"
  alarm_rule        = "ALARM(${var.environment}-api-high-latency) OR ALARM(${var.environment}-api-high-error-rate) OR ALARM(${var.environment}-db-cpu-high) OR ALARM(${var.environment}-redis-memory-high)"
  alarm_actions     = var.alarm_actions
  ok_actions        = var.ok_actions

  tags = {
    Name = "contextforge-${var.environment}-critical"
    Environment = var.environment
  }
}

# =============================================================================
# Dashboard
# =============================================================================
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "contextforge-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "TargetGroup", var.api_target_group_name, "LoadBalancer", var.load_balancer_name, {stat: "p50"}],
            [".", ".", ".", ".", ".", ".", {stat: "p90"}],
            [".", ".", ".", ".", ".", ".", {stat: "p99"}]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "API Latency (p50, p90, p99)"
          period              = 60
          yAxis = {
            left = {
              min = 0
              label = "Milliseconds"
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_2XX_Count", "TargetGroup", var.api_target_group_name, "LoadBalancer", var.load_balancer_name],
            [".", "HTTPCode_Target_4XX_Count", ".", ".", ".", "."],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", ".", "."]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "API Response Codes"
          period              = 60
          yAxis = {
            left = {
              min = 0
              label = "Count"
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", "contextforge-${var.environment}-api"],
            [".", "MemoryUtilization", ".", ".", ".", "."]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "API Service CPU & Memory"
          period              = 60
          yAxis = {
            left = {
              min = 0
              max = 100
              label = "Percent"
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_identifier],
            [".", "DatabaseConnections", ".", "."],
            [".", "FreeStorageSpace", ".", "."],
            [".", "ReadLatency", ".", "."],
            [".", "WriteLatency", ".", "."]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "RDS Metrics"
          period              = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ElastiCache", "CPUUtilization", "CacheClusterId", var.redis_cache_cluster_id],
            [".", "DatabaseMemoryUsagePercentage", ".", "."],
            [".", "CurrConnections", ".", "."],
            [".", "CurrItems", ".", "."],
            [".", "Evictions", ".", "."]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "ElastiCache Redis Metrics"
          period              = 300
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", "contextforge-${var.environment}-worker"],
            [".", "MemoryUtilization", ".", ".", ".", "."],
            [".", "RunningTaskCount", ".", ".", ".", "."]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "Worker Service Metrics"
          period              = 60
          yAxis = {
            left = {
              min = 0
              max = 100
              label = "Percent"
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 24
        height = 6
        properties = {
          metrics = [
            ["ContextForge/Application", "APIErrors"],
            [".", "APIWarnings"],
            [".", "WorkerErrors"]
          ]
          view                = "timeSeries"
          stacked             = false
          region              = var.aws_region
          title               = "Application Errors & Warnings"
          period              = 300
          yAxis = {
            left = {
              min = 0
              label = "Count"
            }
          }
        }
      }
    ]
  })
}

# =============================================================================
# SNS Topic for Alarms
# =============================================================================
resource "aws_sns_topic" "alarms" {
  name = "contextforge-${var.environment}-alarms"

  tags = {
    Name = "contextforge-${var.environment}-alarms"
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn = aws_sns_topic.alarms.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Allow CloudWatch to publish"
        Effect = "Allow"
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }
        Action = "SNS:Publish"
        Resource = aws_sns_topic.alarms.arn
      }
    ]
  })
}

# =============================================================================
# Outputs
# =============================================================================
output "sns_topic_arn" {
  description = "SNS topic ARN for alarms"
  value       = aws_sns_topic.alarms.arn
}

output "dashboard_name" {
  description = "CloudWatch dashboard name"
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}