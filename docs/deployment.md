# ContextForge Deployment Guide

This document provides comprehensive runbooks for deploying, operating, and maintaining ContextForge in production on AWS.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Initial Setup](#initial-setup)
4. [Deployment Procedures](#deployment-procedures)
5. [Blue/Green Deployment](#bluegreen-deployment)
6. [Rollback Procedures](#rollback-procedures)
7. [Secrets Management](#secrets-management)
8. [Monitoring & Alerting](#monitoring--alerting)
9. [Cost Optimization](#cost-optimization)
10. [Troubleshooting](#troubleshooting)
11. [Disaster Recovery](#disaster-recovery)
12. [Security Checklist](#security-checklist)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Region (us-east-1)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Route53    │───▶│     WAF      │───▶│     ALB      │                   │
│  │   (DNS)      │    │  (Rate Limit,│    │  (Public)    │                   │
│  └──────────────┘    │  IP Allowlist)│    └──────┬───────┘                   │
│                      └──────────────┘           │                             │
│                                                 │                             │
│                    ┌────────────────────────────┼────────────────────────┐   │
│                    │                            │                        │   │
│              ┌─────▼─────┐              ┌───────▼───────┐          ┌─────▼─────┐
│              │ API Blue  │              │ MCP Blue      │          │ Worker    │
│              │ Target Grp│              │ Target Grp    │          │ (No LB)   │
│              └─────┬─────┘              └───────┬───────┘          └─────┬─────┘
│                    │                            │                        │   │
│         ┌──────────┼──────────┐       ┌────────┼────────┐       ┌───────┼───────┐
│         ▼          ▼          ▼       ▼        ▼        ▼       ▼       ▼       ▼
│    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│    │API Task│ │API Task│ │API Task│ │MCP Task│ │MCP Task│ │Worker  │ │Worker  │
│    │ (Blue) │ │ (Blue) │ │ (Blue) │ │ (Blue) │ │ (Blue) │ │ Task   │ │ Task   │
│    └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘
│         │          │          │         │         │          │         │
│         └──────────┼──────────┘         └─────────┼──────────┘         │
│                    │                            │                      │
│         ┌──────────▼──────────┐       ┌─────────▼──────────┐    ┌──────▼──────┐
│         │   RDS PostgreSQL    │       │  ElastiCache Redis │    │   S3        │
│         │   (Multi-AZ,        │       │  (Cluster Mode,    │    │   (Documents,│
│         │    pgvector, HNSW)  │       │   Auth, TLS)       │    │   Eval Data)│
│         └─────────────────────┘       └────────────────────┘    └─────────────┘
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                    Observability Stack                                  │  │
│  │  CloudWatch Logs ◀── OTEL Collector ◀── Prometheus ◀── Grafana        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Compute | ECS Fargate | Serverless containers for API, MCP, Worker |
| Load Balancer | ALB + WAF | HTTP/HTTPS termination, Blue/Green routing |
| Database | RDS PostgreSQL 16 + pgvector | Primary vector store with HNSW indexes |
| Cache/Queue | ElastiCache Redis 7 Cluster | Celery broker, rate limiting, caching |
| Storage | S3 (versioned, encrypted) | Documents, eval datasets, model artifacts |
| Secrets | AWS Secrets Manager | All credentials, API keys, certificates |
| Monitoring | CloudWatch + Prometheus + Grafana | Logs, metrics, traces, dashboards |
| CI/CD | GitHub Actions | Automated build, test, deploy |
| IaC | Terraform | Infrastructure as Code |

---

## Prerequisites

### Required Tools

```bash
# AWS CLI v2
aws --version  # >= 2.15.0

# Terraform
terraform --version  # >= 1.8.0

# kubectl (for debugging)
kubectl version --client

# Docker
docker --version

# GitHub CLI (for workflow management)
gh --version

# Python 3.11+ (for local development)
python --version
```

### AWS Permissions

The deployment role needs the following permissions:
- `ec2:*` (VPC, subnets, security groups)
- `ecs:*` (clusters, services, task definitions)
- `ecr:*` (repositories, images)
- `elasticloadbalancing:*` (ALB, target groups, listeners)
- `rds:*` (instances, clusters, parameter groups)
- `elasticache:*` (replication groups, clusters)
- `s3:*` (buckets, objects)
- `secretsmanager:*` (secrets, rotation)
- `iam:*` (roles, policies)
- `cloudwatch:*` (logs, metrics, alarms)
- `wafv2:*` (web ACLs, rules)
- `route53:*` (hosted zones, records)
- `acm:*` (certificates)
- `kms:*` (keys)
- `dynamodb:*` (Terraform state locking)
- `bedrock:*` (model access)

### GitHub Secrets

Configure the following secrets in GitHub repository settings:

| Secret | Description |
|--------|-------------|
| `AWS_ACCOUNT_ID` | 12-digit AWS account ID |
| `AWS_REGION` | AWS region (e.g., us-east-1) |
| `TF_STATE_BUCKET` | S3 bucket for Terraform state |
| `TF_STATE_LOCK_TABLE` | DynamoDB table for state locking |
| `PROD_BLUE_TG_ARN` | Production API Blue target group ARN |
| `PROD_GREEN_TG_ARN` | Production API Green target group ARN |
| `PROD_ALB_LISTENER_ARN` | Production ALB HTTPS listener ARN |
| `PROD_APPROVERS` | GitHub usernames for production approval |
| `OPENAI_API_KEY` | OpenAI API key for embeddings |
| `AWS_ACCESS_KEY_ID` | AWS access key for Bedrock |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key for Bedrock |
| `MCP_CERT` | MCP TLS certificate (PEM) |
| `MCP_KEY` | MCP TLS private key (PEM) |
| `SSL_CERTIFICATE_ARN` | ACM certificate ARN for custom domain |
| `SLACK_WEBHOOK_URL` | Slack webhook for notifications |
| `EVAL_DATASETS_BUCKET` | S3 bucket for evaluation datasets |
| `EVAL_RESULTS_BUCKET` | S3 bucket for evaluation results |

---

## Initial Setup

### 1. Bootstrap AWS Resources

Run the bootstrap script to create initial resources:

```bash
cd infra/terraform

# Initialize Terraform with backend configuration
terraform init \
  -backend-config="bucket=contextforge-terraform-state" \
  -backend-config="key=contextforge/staging/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=contextforge-terraform-locks"

# Plan staging environment
terraform plan \
  -var="environment=staging" \
  -var="aws_region=us-east-1" \
  -out=staging.tfplan

# Apply staging
terraform apply staging.tfplan
```

### 2. Create SSL Certificate

```bash
# Request ACM certificate for custom domain
aws acm request-certificate \
  --domain-name "*.contextforge-staging.dev" \
  --subject-alternative-names "contextforge-staging.dev" "api.contextforge-staging.dev" "mcp.contextforge-staging.dev" \
  --validation-method DNS \
  --region us-east-1
```

### 3. Configure DNS

Create Route53 records pointing to ALB:
- `api.contextforge-staging.dev` → ALB DNS (CNAME)
- `mcp.contextforge-staging.dev` → ALB DNS (CNAME)

### 4. Store Initial Secrets

```bash
# Database password (auto-generated by Terraform, but verify)
aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/database/password \
  --secret-string "your-secure-password"

# Redis password
aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/redis/password \
  --secret-string "your-redis-password"

# Application secret key
aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/app/secret_key \
  --secret-string "your-64-char-secret-key"

# OpenAI API key
aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/openai/api_key \
  --secret-string "sk-..."

# AWS credentials for Bedrock
aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/aws/credentials \
  --secret-string '{"access_key_id":"...","secret_access_key":"...","region":"us-east-1"}'

# MCP certificates
aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/mcp/cert \
  --secret-string "$(cat mcp-cert.pem)"

aws secretsmanager put-secret-value \
  --secret-id contextforge/staging/mcp/key \
  --secret-string "$(cat mcp-key.pem)"
```

### 5. Build and Push Initial Images

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -f docker/Dockerfile.api -t contextforge-staging-api:latest .
docker tag contextforge-staging-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/contextforge-staging-api:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/contextforge-staging-api:latest

# Repeat for worker and MCP
```

### 6. Deploy Initial Services

```bash
# Update ECS services with initial task definitions
aws ecs update-service \
  --cluster contextforge-staging \
  --service contextforge-api-staging \
  --task-definition contextforge-api-staging:1 \
  --force-new-deployment

aws ecs update-service \
  --cluster contextforge-staging \
  --service contextforge-mcp-staging \
  --task-definition contextforge-mcp-staging:1 \
  --force-new-deployment

aws ecs update-service \
  --cluster contextforge-staging \
  --service contextforge-worker-staging \
  --task-definition contextforge-worker-staging:1 \
  --force-new-deployment
```

---

## Deployment Procedures

### Standard Deployment (Staging)

Staging deployments happen automatically on merge to `main` branch:

```bash
# Triggered automatically by GitHub Actions
# Or manually:
gh workflow run cd-staging.yml -f image_tag=v1.2.3
```

### Production Deployment

Production deployments require a version tag and manual approval:

```bash
# Create and push a version tag
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3

# This triggers the CD Production workflow with manual approval
# Or manually with specific version:
gh workflow run cd-prod.yml -f version=v1.2.3
```

### Emergency Hotfix

For critical production fixes bypassing normal flow:

```bash
# Use workflow dispatch with skip_approval (use sparingly!)
gh workflow run cd-prod.yml -f version=v1.2.4 -f skip_approval=true

# Requires admin approval in GitHub Actions
```

---

## Blue/Green Deployment

ContextForge uses ALB target group swapping for zero-downtime Blue/Green deployments.

### How It Works

1. **Two Target Groups**: Blue and Green for each service (API, MCP)
2. **Active Group**: Receives 100% of production traffic
3. **Inactive Group**: Receives 0% traffic, used for staging new version
4. **Swap**: Instant DNS-level switch by modifying ALB listener rule

### Deployment Flow

```
1. Build new Docker images → Push to ECR
2. Register new task definitions with new image tags
3. Update INACTIVE target group services (Blue→Green or Green→Blue)
4. Wait for services to stabilize (health checks pass)
5. Verify health endpoints on inactive targets
6. Modify ALB listener rule → Switch traffic to new target group
7. Verify production health after swap
8. Update the other target group for next deployment
9. Record deployment in DynamoDB
```

### Manual Blue/Green Swap

If needed, manually swap target groups:

```bash
# Check current active target group
aws elbv2 describe-rules --listener-arn $PROD_ALB_LISTENER_ARN \
  --query 'Rules[?Priority!=`default`].{Priority:Priority,TargetGroup:Actions[0].TargetGroupArn}'

# Swap to other target group
aws elbv2 modify-rule \
  --rule-arn $RULE_ARN \
  --actions Type=forward,TargetGroupArn=$OTHER_TG_ARN
```

### Verification Steps

After swap, verify:
```bash
# Health check
curl -f https://api.contextforge-prod.com/health

# API functionality
curl -X POST https://api.contextforge-prod.com/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 1}'

# Check target group health
aws elbv2 describe-target-health --target-group-arn $ACTIVE_TG_ARN
```

---

## Rollback Procedures

### Automatic Rollback (CI/CD)

The CD pipelines include automatic rollback on failure:
- Health check failures trigger immediate rollback
- Traffic switches back to previous target group
- Previous task definition is redeployed
- Deployment recorded as failed in DynamoDB

### Manual Rollback

```bash
# 1. Identify previous task definition revision
CURRENT_REV=$(aws ecs describe-task-definition \
  --task-definition contextforge-api-prod \
  --query 'taskDefinition.revision' --output text)
PREV_REV=$((CURRENT_REV - 1))

# 2. Get previous task definition ARN
PREV_TD_ARN=$(aws ecs describe-task-definition \
  --task-definition contextforge-api-prod:$PREV_REV \
  --query 'taskDefinition.taskDefinitionArn' --output text)

# 3. Update service to previous revision
aws ecs update-service \
  --cluster contextforge-prod \
  --service contextforge-api-prod-blue \
  --task-definition $PREV_TD_ARN \
  --force-new-deployment

# 4. If using Blue/Green, also swap target group back
aws elbv2 modify-rule \
  --rule-arn $RULE_ARN \
  --actions Type=forward,TargetGroupArn=$PREVIOUS_TG_ARN

# 5. Verify rollback
curl -f https://api.contextforge-prod.com/health
```

### Database Rollback

For schema migrations:

```bash
# List migrations
aws rds describe-db-instances --db-instance-identifier contextforge-prod \
  --query 'DBInstances[0].PendingModifiedValues'

# Restore from snapshot (if needed)
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier contextforge-prod-restored \
  --db-snapshot-identifier contextforge-prod-snapshot-20240115 \
  --db-subnet-group-name contextforge-prod-db-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxxx
```

---

## Secrets Management

### Rotation Schedule

| Secret | Rotation Frequency | Method |
|--------|-------------------|--------|
| Database Password | 90 days | Lambda rotation function |
| Redis Auth Token | 90 days | Manual + Terraform |
| Application Secret Key | 180 days | Manual |
| OpenAI API Key | As needed | Manual |
| AWS Credentials | 90 days | IAM key rotation |
| MCP Certificates | 365 days | ACM renewal |

### Rotating Database Password

```bash
# 1. Trigger rotation via Secrets Manager
aws secretsmanager rotate-secret \
  --secret-id contextforge/prod/database/password

# 2. Monitor rotation status
aws secretsmanager describe-secret \
  --secret-id contextforge/prod/database/password \
  --query 'RotationRules.AutomaticallyAfterDays'

# 3. Verify applications reconnect
aws ecs update-service \
  --cluster contextforge-prod \
  --service contextforge-api-prod-blue \
  --force-new-deployment
```

### Adding New Secrets

```bash
# Create secret
aws secretsmanager create-secret \
  --name contextforge/prod/new-service/api_key \
  --description "API key for new service integration" \
  --secret-string "your-api-key"

# Grant ECS task role access
aws secretsmanager put-resource-policy \
  --secret-id contextforge/prod/new-service/api_key \
  --resource-policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789012:role/contextforge-prod-ecs-task-role"},
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "*"
    }]
  }'
```

---

## Monitoring & Alerting

### Key Dashboards

1. **Grafana: ContextForge Overview** - `https://grafana.contextforge.com/d/contextforge-overview`
2. **CloudWatch: ECS Service Metrics** - Service CPU, Memory, Task count
3. **CloudWatch: ALB Metrics** - Latency, Error rates, Request count
4. **CloudWatch: RDS Metrics** - CPU, Connections, Storage, Latency
5. **CloudWatch: ElastiCache Metrics** - Memory, CPU, Connections, Evictions

### Critical Alarms

| Alarm | Threshold | Action |
|-------|-----------|--------|
| API P99 Latency | > 2s for 3 periods | Page on-call |
| API 5xx Error Rate | > 1% for 3 periods | Page on-call |
| Worker Queue Depth | > 1000 for 2 periods | Alert on-call |
| RDS CPU | > 80% for 3 periods | Alert on-call |
| Redis Memory | > 85% for 3 periods | Alert on-call |
| ECS Service CPU | > 80% for 3 periods | Auto-scale + Alert |
| Estimated Charges | > $5000/month | Alert finance |

### Log Queries

```bash
# API errors in last hour
aws logs filter-log-events \
  --log-group-name /ecs/contextforge-prod/api \
  --start-time $(date -d '1 hour ago' +%s)000 \
  --filter-pattern "ERROR"

# Slow queries
aws logs filter-log-events \
  --log-group-name /ecs/contextforge-prod/api \
  --filter-pattern "duration > 5000"

# Worker task failures
aws logs filter-log-events \
  --log-group-name /ecs/contextforge-prod/worker \
  --filter-pattern "FAILED"
```

---

## Cost Optimization

### Current Monthly Estimates (Production)

| Resource | Configuration | Est. Monthly Cost |
|----------|---------------|-------------------|
| ECS Fargate API | 3 tasks × 2 vCPU, 4 GB | ~$450 |
| ECS Fargate MCP | 2 tasks × 1 vCPU, 2 GB | ~$150 |
| ECS Fargate Worker | 3 tasks × 4 vCPU, 8 GB (Spot) | ~$600 |
| RDS PostgreSQL | db.r6g.xlarge Multi-AZ, 500 GB | ~$800 |
| ElastiCache Redis | 2 shards × cache.r6g.xlarge | ~$600 |
| ALB | 1 ALB + 4 target groups | ~$50 |
| CloudWatch | Logs, Metrics, Alarms | ~$200 |
| S3 | 1 TB storage, 10M requests | ~$50 |
| Data Transfer | ~5 TB/month | ~$450 |
| **Total** | | **~$3,350/month** |

### Optimization Strategies

1. **Fargate Spot for Workers**: Workers use Spot capacity (70% savings)
2. **Right-sizing**: Monitor CPU/Memory utilization and adjust
3. **RDS Storage Autoscaling**: Enabled up to 1 TB
4. **ElastiCache Cluster Mode**: Scale shards horizontally
5. **S3 Lifecycle**: Auto-expire old document versions (90 days)
6. **CloudWatch Log Retention**: 30 days default, adjust per log group

### Cost Monitoring

```bash
# Check current month charges
aws ce get-cost-and-usage \
  --time-period Start=$(date -d "$(date +%Y-%m-01)" +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE
```

---

## Troubleshooting

### Common Issues

#### API Returns 503 Service Unavailable

```bash
# Check service status
aws ecs describe-services \
  --cluster contextforge-prod \
  --services contextforge-api-prod-blue contextforge-api-prod-green

# Check task health
aws ecs list-tasks --cluster contextforge-prod --service-name contextforge-api-prod-blue
aws ecs describe-tasks --cluster contextforge-prod --tasks $TASK_ARNS

# Check target group health
aws elbv2 describe-target-health --target-group-arn $TG_ARN
```

#### High Latency / Timeouts

```bash
# Check ALB target response time
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name TargetResponseTime \
  --dimensions Name=TargetGroup,Value=$TG_NAME Name=LoadBalancer,Value=$ALB_NAME \
  --start-time $(date -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date +%Y-%m-%dT%H:%M:%S) \
  --period 60 --statistics p99

# Check RDS performance
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=contextforge-prod \
  --period 300 --statistics Average

# Check for slow queries in logs
aws logs filter-log-events \
  --log-group-name /aws/rds/contextforge-prod/postgresql \
  --filter-pattern "duration > 1000"
```

#### Worker Tasks Stuck / Queue Backing Up

```bash
# Check queue depth
aws cloudwatch get-metric-statistics \
  --namespace AWS/SQS \
  --metric-name ApproximateNumberOfMessagesVisible \
  --dimensions Name=QueueName,Value=contextforge-prod-celery \
  --period 300 --statistics Average

# Check worker task status
aws ecs describe-tasks \
  --cluster contextforge-prod \
  --tasks $(aws ecs list-tasks --cluster contextforge-prod --service-name contextforge-worker-prod --query 'taskArns[]' --output text)

# Scale up workers
aws ecs update-service \
  --cluster contextforge-prod \
  --service contextforge-worker-prod \
  --desired-count 10
```

#### Database Connection Issues

```bash
# Check RDS connections
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=contextforge-prod \
  --period 300 --statistics Maximum

# Check for connection leaks in application logs
aws logs filter-log-events \
  --log-group-name /ecs/contextforge-prod/api \
  --filter-pattern "connection pool"
```

#### Redis Memory Pressure

```bash
# Check memory usage
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name DatabaseMemoryUsagePercentage \
  --dimensions Name=CacheClusterId,Value=contextforge-prod-xxx \
  --period 300 --statistics Average

# Check evictions
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name Evictions \
  --dimensions Name=CacheClusterId,Value=contextforge-prod-xxx \
  --period 300 --statistics Sum

# Flush cache if needed (careful!)
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD FLUSHALL
```

### Debugging Commands

```bash
# Get ECS task logs
aws logs get-log-events \
  --log-group-name /ecs/contextforge-prod/api \
  --log-stream-name api-blue/xxxxxxxx \
  --limit 100

# Execute command in running task
aws ecs execute-command \
  --cluster contextforge-prod \
  --task $TASK_ARN \
  --container api \
  --command "/bin/bash" \
  --interactive

# Check task definition
aws ecs describe-task-definition \
  --task-definition contextforge-api-prod-blue:5 \
  --query 'taskDefinition.containerDefinitions[0]'

# View CloudFormation stack events (if using CFN)
aws cloudformation describe-stack-events --stack-name contextforge-prod
```

---

## Disaster Recovery

### RTO/RPO Targets

| Component | RTO | RPO |
|-----------|-----|-----|
| API/MCP Services | 5 minutes | 0 (stateless) |
| Worker Services | 10 minutes | 0 (stateless) |
| PostgreSQL Database | 30 minutes | 5 minutes |
| Redis Cache | 15 minutes | N/A (rebuildable) |
| S3 Documents | 1 hour | 0 (versioned) |

### Backup Strategy

1. **RDS**: Automated daily snapshots, 30-day retention, point-in-time recovery
2. **Redis**: Daily snapshots, 7-day retention
3. **S3**: Versioning enabled, cross-region replication to us-west-2
4. **Terraform State**: S3 versioning + DynamoDB locking
5. **Secrets**: Automatic rotation, 30-day recovery window

### DR Procedures

#### Region Failover (us-east-1 → us-west-2)

```bash
# 1. Promote RDS read replica in us-west-2
aws rds promote-read-replica \
  --db-instance-identifier contextforge-dr-replica \
  --region us-west-2

# 2. Update Route53 to point to DR ALB
aws route53 change-resource-record-sets \
  --hosted-zone-id $ZONE_ID \
  --change-batch file://dr-failover.json

# 3. Scale up ECS services in DR region
aws ecs update-service \
  --cluster contextforge-dr \
  --service contextforge-api-dr \
  --desired-count 3 \
  --region us-west-2

# 4. Verify DR environment
curl -f https://api.contextforge-dr.com/health
```

#### Data Recovery from Backup

```bash
# Restore RDS from snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier contextforge-prod-restored \
  --db-snapshot-identifier contextforge-prod-snapshot-20240115-0300 \
  --db-instance-class db.r6g.xlarge \
  --db-subnet-group-name contextforge-prod-db-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxxx \
  --multi-az \
  --region us-east-1

# Wait for restore, then rename
aws rds modify-db-instance \
  --db-instance-identifier contextforge-prod-restored \
  --new-db-instance-identifier contextforge-prod \
  --apply-immediately
```

---

## Security Checklist

### Pre-Deployment

- [ ] All secrets stored in Secrets Manager (no plaintext in code/ENV)
- [ ] TLS 1.2+ enforced on ALB (ELBSecurityPolicy-TLS13-1-2-2021-06)
- [ ] WAF enabled with rate limiting and IP allowlist for MCP
- [ ] Security groups follow least privilege
- [ ] VPC endpoints for all AWS services (no internet access from private subnets)
- [ ] Database encryption at rest (KMS) and in transit (TLS)
- [ ] Redis encryption at rest (KMS) and in transit (TLS)
- [ ] S3 buckets encrypted, versioned, public access blocked
- [ ] IAM roles follow least privilege principle
- [ ] Container images scanned for vulnerabilities (ECR scan on push)
- [ ] Non-root user in all containers
- [ ] Distroless/minimal base images where possible

### Post-Deployment

- [ ] Verify WAF rules blocking malicious traffic
- [ ] Confirm CloudTrail logging enabled for all regions
- [ ] Enable GuardDuty for threat detection
- [ ] Configure Security Hub for compliance monitoring
- [ ] Set up Config rules for drift detection
- [ ] Schedule regular penetration testing
- [ ] Review and update security group rules quarterly
- [ ] Rotate all credentials per schedule
- [ ] Monitor for CVE updates in base images
- [ ] Conduct annual security audit

### Incident Response

1. **Contain**: Revoke compromised credentials, modify security groups
2. **Assess**: Check CloudTrail, GuardDuty, VPC Flow Logs
3. **Recover**: Rotate all potentially compromised secrets
4. **Document**: Record timeline, actions, lessons learned
5. **Improve**: Update runbooks, add detection rules

---

## Appendix: Useful Commands

### Terraform

```bash
# Format code
terraform fmt -recursive

# Validate
terraform validate

# Plan with specific variables
terraform plan -var="environment=prod" -var="aws_region=us-east-1"

# Import existing resource
terraform import aws_ecs_cluster.main contextforge-prod

# State management
terraform state list
terraform state show aws_ecs_service.api_blue
terraform state rm aws_ecs_service.api_blue
```

### ECS

```bash
# List services
aws ecs list-services --cluster contextforge-prod

# Describe service
aws ecs describe-services --cluster contextforge-prod --services contextforge-api-prod-blue

# Update service (force new deployment)
aws ecs update-service --cluster contextforge-prod --service contextforge-api-prod-blue --force-new-deployment

# Scale service
aws ecs update-service --cluster contextforge-prod --service contextforge-worker-prod --desired-count 10

# Get task definition
aws ecs describe-task-definition --task-definition contextforge-api-prod-blue:5
```

### ALB/WAF

```bash
# List target groups
aws elbv2 describe-target-groups --load-balancer-arn $ALB_ARN

# Describe target health
aws elbv2 describe-target-health --target-group-arn $TG_ARN

# Modify listener rule (Blue/Green swap)
aws elbv2 modify-rule --rule-arn $RULE_ARN --actions Type=forward,TargetGroupArn=$NEW_TG_ARN

# Get WAF metrics
aws wafv2 get-sampled-requests --web-acl-arn $WAF_ARN --rule-metric-name ContextForgeWAF --scope REGIONAL --time-window StartTime=2024-01-15T00:00:00Z,EndTime=2024-01-15T01:00:00Z --max-items 100
```

### Secrets

```bash
# Get secret value
aws secretsmanager get-secret-value --secret-id contextforge/prod/database/password --query SecretString --output text

# List secrets
aws secretsmanager list-secrets --filters Key=name,Values=contextforge/prod

# Rotate secret
aws secretsmanager rotate-secret --secret-id contextforge/prod/database/password
```

---

## Support Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Platform Team | #platform-team (Slack) | PagerDuty: platform-oncall |
| Database Admin | #dba-team (Slack) | PagerDuty: dba-oncall |
| Security Team | #security-team (Slack) | PagerDuty: security-oncall |
| AWS Support | Enterprise Support Case | TAM: aws-tam@contextforge.com |

---

*Last Updated: 2024-11-24*
*Version: 1.0.0*