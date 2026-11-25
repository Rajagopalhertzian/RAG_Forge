# Security Groups Module for ContextForge

# =============================================================================
# ALB Security Group
# =============================================================================
resource "aws_security_group" "alb" {
  name        = "contextforge-${var.environment}-alb-sg"
  description = "Security group for Application Load Balancer"
  vpc_id      = var.vpc_id

  # HTTP/HTTPS from allowed CIDRs
  dynamic "ingress" {
    for_each = var.alb_ingress_cidrs
    content {
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "HTTP from ${ingress.value}"
    }
  }

  dynamic "ingress" {
    for_each = var.alb_ingress_cidrs
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "HTTPS from ${ingress.value}"
    }
  }

  # Health checks from ALB itself
  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Health checks from ALB"
  }

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Health checks from ALB (HTTPS)"
  }

  # Outbound to targets
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name = "contextforge-${var.environment}-alb-sg"
  }
}

# =============================================================================
# ECS Tasks Security Group
# =============================================================================
resource "aws_security_group" "ecs" {
  name        = "contextforge-${var.environment}-ecs-sg"
  description = "Security group for ECS tasks"
  vpc_id      = var.vpc_id

  # Ingress from ALB
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "API from ALB"
  }

  ingress {
    from_port       = 8001
    to_port         = 8001
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "MCP from ALB"
  }

  # Ingress from bastion for debugging
  dynamic "ingress" {
    for_each = var.bastion_ingress_cidrs
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "SSH from bastion ${ingress.value}"
    }
  }

  # Outbound to database, Redis, internet (via NAT)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name = "contextforge-${var.environment}-ecs-sg"
  }
}

# =============================================================================
# RDS Security Group
# =============================================================================
resource "aws_security_group" "rds" {
  name        = "contextforge-${var.environment}-rds-sg"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = var.vpc_id

  # Ingress from ECS tasks
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
    description     = "PostgreSQL from ECS tasks"
  }

  # Ingress from bastion
  dynamic "ingress" {
    for_each = var.bastion_ingress_cidrs
    content {
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "PostgreSQL from bastion ${ingress.value}"
    }
  }

  # No outbound needed for RDS (initiates no connections)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name = "contextforge-${var.environment}-rds-sg"
  }
}

# =============================================================================
# ElastiCache Security Group
# =============================================================================
resource "aws_security_group" "elasticache" {
  name        = "contextforge-${var.environment}-elasticache-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = var.vpc_id

  # Ingress from ECS tasks
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
    description     = "Redis from ECS tasks"
  }

  # Ingress from bastion
  dynamic "ingress" {
    for_each = var.bastion_ingress_cidrs
    content {
      from_port   = 6379
      to_port     = 6379
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "Redis from bastion ${ingress.value}"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name = "contextforge-${var.environment}-elasticache-sg"
  }
}

# =============================================================================
# Bastion Security Group (if needed)
# =============================================================================
resource "aws_security_group" "bastion" {
  count  = length(var.bastion_ingress_cidrs) > 0 ? 1 : 0
  name        = "contextforge-${var.environment}-bastion-sg"
  description = "Security group for bastion host"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.bastion_ingress_cidrs
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "SSH from ${ingress.value}"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name = "contextforge-${var.environment}-bastion-sg"
  }
}

# =============================================================================
# Outputs
# =============================================================================
output "alb_sg_id" {
  description = "ALB security group ID"
  value       = aws_security_group.alb.id
}

output "ecs_sg_id" {
  description = "ECS security group ID"
  value       = aws_security_group.ecs.id
}

output "rds_sg_id" {
  description = "RDS security group ID"
  value       = aws_security_group.rds.id
}

output "elasticache_sg_id" {
  description = "ElastiCache security group ID"
  value       = aws_security_group.elasticache.id
}

output "bastion_sg_id" {
  description = "Bastion security group ID"
  value       = length(aws_security_group.bastion) > 0 ? aws_security_group.bastion[0].id : null
}