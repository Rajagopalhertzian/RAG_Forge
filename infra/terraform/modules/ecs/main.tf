# ECS Cluster & Services Module for ContextForge

# =============================================================================
# ECS Cluster
# =============================================================================
resource "aws_ecs_cluster" "main" {
  name = "contextforge-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = "/ecs/contextforge-${var.environment}/exec"
        cloud_watch_encryption_enabled = true
      }
    }
  }

  tags = {
    Name = "contextforge-${var.environment}-cluster"
  }
}

# =============================================================================
# CloudWatch Log Groups
# =============================================================================
resource "aws_cloudwatch_log_group" "ecs_exec" {
  name              = "/ecs/contextforge-${var.environment}/exec"
  retention_in_days = 30
}

# =============================================================================
# ECR Repositories
# =============================================================================
resource "aws_ecr_repository" "repos" {
  for_each = var.ecr_repositories

  name                 = each.value
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = each.value
  }
}

# =============================================================================
# ECR Lifecycle Policies (separate resource for manageability)
# =============================================================================
resource "aws_ecr_lifecycle_policy" "repos" {
  for_each = var.ecr_repositories

  repository = each.value
  policy     = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 30 tagged images"
        selection = {
          tagStatus     = "tagged"
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus     = "untagged"
          countType     = "sinceImagePushed"
          countNumber   = 7
          countUnit     = "days"
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# =============================================================================
# Blue/Green Target Groups for API
# =============================================================================
resource "aws_lb_target_group" "api_blue" {
  name        = "contextforge-${var.environment}-api-blue"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.api_service.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "contextforge-${var.environment}-api-blue"
    Color = "blue"
  }
}

resource "aws_lb_target_group" "api_green" {
  name        = "contextforge-${var.environment}-api-green"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.api_service.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "contextforge-${var.environment}-api-green"
    Color = "green"
  }
}

# =============================================================================
# Blue/Green Target Groups for MCP
# =============================================================================
resource "aws_lb_target_group" "mcp_blue" {
  name        = "contextforge-${var.environment}-mcp-blue"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.mcp_service.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "contextforge-${var.environment}-mcp-blue"
    Color = "blue"
  }
}

resource "aws_lb_target_group" "mcp_green" {
  name        = "contextforge-${var.environment}-mcp-green"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.mcp_service.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "contextforge-${var.environment}-mcp-green"
    Color = "green"
  }
}

# =============================================================================
# Task Definitions - API (Blue)
# =============================================================================
resource "aws_ecs_task_definition" "api_blue" {
  family                   = "contextforge-${var.environment}-api-blue"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.api_service.cpu
  memory                   = var.api_service.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${var.ecr_repositories.api}:latest"
    cpu       = var.api_service.cpu
    memory    = var.api_service.memory
    essential = true
    portMappings = [{
      containerPort = var.api_service.container_port
      protocol      = "tcp"
    }]
    environment = [
      for k, v in var.api_service.environment_variables : {
        name  = k
        value = v
      }
    ]
    secrets = [
      for s in var.api_service.secrets : {
        name      = s.name
        valueFrom = s.valueFrom
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/contextforge-${var.environment}/api"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api-blue"
      }
    }
    healthCheck = {
      command  = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval = 30
      timeout  = 10
      retries  = 3
      startPeriod = 60
    }
  }])

  tags = {
    Name = "contextforge-${var.environment}-api-blue"
  }
}

# =============================================================================
# Task Definitions - API (Green)
# =============================================================================
resource "aws_ecs_task_definition" "api_green" {
  family                   = "contextforge-${var.environment}-api-green"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.api_service.cpu
  memory                   = var.api_service.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${var.ecr_repositories.api}:latest"
    cpu       = var.api_service.cpu
    memory    = var.api_service.memory
    essential = true
    portMappings = [{
      containerPort = var.api_service.container_port
      protocol      = "tcp"
    }]
    environment = [
      for k, v in var.api_service.environment_variables : {
        name  = k
        value = v
      }
    ]
    secrets = [
      for s in var.api_service.secrets : {
        name      = s.name
        valueFrom = s.valueFrom
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/contextforge-${var.environment}/api"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api-green"
      }
    }
    healthCheck = {
      command  = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval = 30
      timeout  = 10
      retries  = 3
      startPeriod = 60
    }
  }])

  tags = {
    Name = "contextforge-${var.environment}-api-green"
  }
}

# =============================================================================
# Task Definitions - MCP (Blue)
# =============================================================================
resource "aws_ecs_task_definition" "mcp_blue" {
  family                   = "contextforge-${var.environment}-mcp-blue"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.mcp_service.cpu
  memory                   = var.mcp_service.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name      = "mcp"
    image     = "${var.ecr_repositories.mcp}:latest"
    cpu       = var.mcp_service.cpu
    memory    = var.mcp_service.memory
    essential = true
    portMappings = [{
      containerPort = var.mcp_service.container_port
      protocol      = "tcp"
    }]
    environment = [
      for k, v in var.mcp_service.environment_variables : {
        name  = k
        value = v
      }
    ]
    secrets = [
      for s in var.mcp_service.secrets : {
        name      = s.name
        valueFrom = s.valueFrom
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/contextforge-${var.environment}/mcp"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mcp-blue"
      }
    }
    healthCheck = {
      command  = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
      interval = 30
      timeout  = 10
      retries  = 3
      startPeriod = 60
    }
  }])

  tags = {
    Name = "contextforge-${var.environment}-mcp-blue"
  }
}

# =============================================================================
# Task Definitions - MCP (Green)
# =============================================================================
resource "aws_ecs_task_definition" "mcp_green" {
  family                   = "contextforge-${var.environment}-mcp-green"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.mcp_service.cpu
  memory                   = var.mcp_service.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name      = "mcp"
    image     = "${var.ecr_repositories.mcp}:latest"
    cpu       = var.mcp_service.cpu
    memory    = var.mcp_service.memory
    essential = true
    portMappings = [{
      containerPort = var.mcp_service.container_port
      protocol      = "tcp"
    }]
    environment = [
      for k, v in var.mcp_service.environment_variables : {
        name  = k
        value = v
      }
    ]
    secrets = [
      for s in var.mcp_service.secrets : {
        name      = s.name
        valueFrom = s.valueFrom
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/contextforge-${var.environment}/mcp"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mcp-green"
      }
    }
    healthCheck = {
      command  = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
      interval = 30
      timeout  = 10
      retries  = 3
      startPeriod = 60
    }
  }])

  tags = {
    Name = "contextforge-${var.environment}-mcp-green"
  }
}

# =============================================================================
# Task Definition - Worker
# =============================================================================
resource "aws_ecs_task_definition" "worker" {
  family                   = "contextforge-${var.environment}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.worker_service.cpu
  memory                   = var.worker_service.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${var.ecr_repositories.worker}:latest"
    cpu       = var.worker_service.cpu
    memory    = var.worker_service.memory
    essential = true
    environment = [
      for k, v in var.worker_service.environment_variables : {
        name  = k
        value = v
      }
    ]
    secrets = [
      for s in var.worker_service.secrets : {
        name      = s.name
        valueFrom = s.valueFrom
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/contextforge-${var.environment}/worker"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
    healthCheck = {
      command  = ["CMD-SHELL", "celery -A contextforge.workers.celery_app inspect ping || exit 1"]
      interval = 60
      timeout  = 30
      retries  = 3
      startPeriod = 120
    }
  }])

  tags = {
    Name = "contextforge-${var.environment}-worker"
  }
}

# =============================================================================
# ECS Services - API Blue
# =============================================================================
resource "aws_ecs_service" "api_blue" {
  name            = "contextforge-${var.environment}-api-blue"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api_blue.arn
  desired_count   = var.api_service.desired_count
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_blue.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Name = "contextforge-${var.environment}-api-blue"
    Color = "blue"
  }
}

# =============================================================================
# ECS Services - API Green
# =============================================================================
resource "aws_ecs_service" "api_green" {
  name            = "contextforge-${var.environment}-api-green"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api_green.arn
  desired_count   = 0  # Start with 0 for Blue/Green
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_green.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Name = "contextforge-${var.environment}-api-green"
    Color = "green"
  }
}

# =============================================================================
# ECS Services - MCP Blue
# =============================================================================
resource "aws_ecs_service" "mcp_blue" {
  name            = "contextforge-${var.environment}-mcp-blue"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mcp_blue.arn
  desired_count   = var.mcp_service.desired_count
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mcp_blue.arn
    container_name   = "mcp"
    container_port   = 8001
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Name = "contextforge-${var.environment}-mcp-blue"
    Color = "blue"
  }
}

# =============================================================================
# ECS Services - MCP Green
# =============================================================================
resource "aws_ecs_service" "mcp_green" {
  name            = "contextforge-${var.environment}-mcp-green"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mcp_green.arn
  desired_count   = 0  # Start with 0 for Blue/Green
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mcp_green.arn
    container_name   = "mcp"
    container_port   = 8001
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Name = "contextforge-${var.environment}-mcp-green"
    Color = "green"
  }
}

# =============================================================================
# ECS Service - Worker
# =============================================================================
resource "aws_ecs_service" "worker" {
  name            = "contextforge-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_service.desired_count
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  # No load balancer for worker

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  tags = {
    Name = "contextforge-${var.environment}-worker"
  }
}

# =============================================================================
# Service Auto Scaling - API
# =============================================================================
resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.api_service.max_capacity
  min_capacity       = var.api_service.min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api_blue.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "contextforge-${var.environment}-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "api_memory" {
  name               = "contextforge-${var.environment}-api-memory-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 80.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# =============================================================================
# Service Auto Scaling - MCP
# =============================================================================
resource "aws_appautoscaling_target" "mcp" {
  max_capacity       = var.mcp_service.max_capacity
  min_capacity       = var.mcp_service.min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.mcp_blue.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "mcp_cpu" {
  name               = "contextforge-${var.environment}-mcp-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.mcp.resource_id
  scalable_dimension = aws_appautoscaling_target.mcp.scalable_dimension
  service_namespace  = aws_appautoscaling_target.mcp.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# =============================================================================
# Service Auto Scaling - Worker
# =============================================================================
resource "aws_appautoscaling_target" "worker" {
  max_capacity       = var.worker_service.max_capacity
  min_capacity       = var.worker_service.min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "worker_cpu" {
  name               = "contextforge-${var.environment}-worker-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# =============================================================================
# Outputs
# =============================================================================
output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "api_blue_target_group_arn" {
  description = "API Blue target group ARN"
  value       = aws_lb_target_group.api_blue.arn
}

output "api_green_target_group_arn" {
  description = "API Green target group ARN"
  value       = aws_lb_target_group.api_green.arn
}

output "mcp_blue_target_group_arn" {
  description = "MCP Blue target group ARN"
  value       = aws_lb_target_group.mcp_blue.arn
}

output "mcp_green_target_group_arn" {
  description = "MCP Green target group ARN"
  value       = aws_lb_target_group.mcp_green.arn
}

output "api_target_group_name" {
  description = "API target group name (for CloudWatch)"
  value       = aws_lb_target_group.api_blue.name
}

output "ecr_api_repository_url" {
  description = "ECR API repository URL"
  value       = aws_ecr_repository.repos["api"].repository_url
}

output "ecr_mcp_repository_url" {
  description = "ECR MCP repository URL"
  value       = aws_ecr_repository.repos["mcp"].repository_url
}

output "ecr_worker_repository_url" {
  description = "ECR Worker repository URL"
  value       = aws_ecr_repository.repos["worker"].repository_url
}

output "api_task_definition_blue_arn" {
  description = "API Blue task definition ARN"
  value       = aws_ecs_task_definition.api_blue.arn
}

output "api_task_definition_green_arn" {
  description = "API Green task definition ARN"
  value       = aws_ecs_task_definition.api_green.arn
}

output "mcp_task_definition_blue_arn" {
  description = "MCP Blue task definition ARN"
  value       = aws_ecs_task_definition.mcp_blue.arn
}

output "mcp_task_definition_green_arn" {
  description = "MCP Green task definition ARN"
  value       = aws_ecs_task_definition.mcp_green.arn
}

output "worker_task_definition_arn" {
  description = "Worker task definition ARN"
  value       = aws_ecs_task_definition.worker.arn
}