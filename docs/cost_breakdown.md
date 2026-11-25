# ContextForge AWS Cost Breakdown

> **Last Updated:** 2024-11-24  
> **Region:** us-east-1 (N. Virginia)  
> **Currency:** USD/month

---

## Executive Summary

| Environment | Estimated Monthly Cost | With Fargate Spot (Workers) |
|-------------|----------------------|----------------------------|
| **Staging** | ~$420/mo | ~$350/mo |
| **Production** | ~$1,250/mo | ~$980/mo |

> **Note:** Costs are estimates based on AWS on-demand pricing (Nov 2024). Actual costs vary by usage, data transfer, and reserved instances/savings plans.

---

## Per-Service Monthly Estimates

### Staging Environment

| Service | Configuration | Monthly Cost | Notes |
|---------|--------------|--------------|-------|
| **ECS Fargate (API)** | 1 task × 1 vCPU / 2 GB × 730 hrs | $44.00 | 1 task, auto-scale min=1, max=3 |
| **ECS Fargate (MCP)** | 1 task × 0.5 vCPU / 1 GB × 730 hrs | $15.50 | 1 task, auto-scale min=1, max=2 |
| **ECS Fargate (Worker)** | 1 task × 2 vCPU / 4 GB × 730 hrs | $88.00 | 1 task, auto-scale min=1, max=5 |
| **RDS PostgreSQL** | db.t3.medium (2 vCPU, 4 GB) + 100 GB gp3 | $78.00 | Single-AZ, pgvector enabled |
| **ElastiCache Redis** | cache.t3.micro (2 vCPU, 0.5 GB) | $14.50 | Single node, no replication |
| **Application Load Balancer** | 1 ALB + 2 target groups | $22.50 | ~1M requests, 50 GB data |
| **CloudWatch Logs** | 5 GB ingest, 50 GB storage | $5.50 | Retention: 30 days |
| **CloudWatch Metrics** | 50 custom metrics, 1M API calls | $3.50 | |
| **S3 (State + Artifacts)** | 10 GB storage, 1M requests | $0.30 | |
| **Data Transfer** | 100 GB out to Internet | $9.00 | First 100 GB/mo free tier |
| **WAF (Optional)** | 1 Web ACL, 10 rules, 1M requests | $5.00 | If enabled |
| **Route 53** | 1 hosted zone, 1M queries | $0.50 | |
| **Secrets Manager** | 10 secrets, 100K API calls | $5.00 | |
| **ECR** | 3 repos, 30 images each, 5 GB | $0.50 | Lifecycle: keep 30, expire untagged 7d |
| **VPC/NAT Gateway** | 1 NAT Gateway (staging) | $45.00 | 730 hrs + data processing |
| **Total Staging** | | **~$337/mo** | **~$420/mo with buffer** |

---

### Production Environment

| Service | Configuration | Monthly Cost | Notes |
|---------|--------------|--------------|-------|
| **ECS Fargate (API)** | 3 tasks × 2 vCPU / 4 GB × 730 hrs | $396.00 | Blue/Green: 3 blue + 0 green (scale to 6 during deploy) |
| **ECS Fargate (MCP)** | 2 tasks × 1 vCPU / 2 GB × 730 hrs | $132.00 | Blue/Green: 2 blue + 0 green |
| **ECS Fargate (Worker)** | 3 tasks × 4 vCPU / 8 GB × 730 hrs | $792.00 | Fargate Spot eligible (see savings below) |
| **ECS Fargate (Beat)** | 1 task × 0.5 vCPU / 1 GB × 730 hrs | $15.50 | Single scheduler |
| **RDS PostgreSQL** | db.r6g.xlarge (4 vCPU, 32 GB) + 500 GB gp3 | $385.00 | Multi-AZ, provisioned IOPS: 3000 |
| **ElastiCache Redis** | cache.r6g.xlarge (4 vCPU, 32 GB) × 2 (replication) | $310.00 | Cluster mode, 1 primary + 1 replica |
| **Application Load Balancer** | 1 ALB + 4 target groups (blue/green) | $45.00 | ~10M requests, 500 GB data |
| **CloudWatch Logs** | 50 GB ingest, 500 GB storage | $55.00 | Retention: 90 days |
| **CloudWatch Metrics** | 200 custom metrics, 10M API calls | $15.00 | |
| **S3 (State + Artifacts + Backups)** | 500 GB storage, 10M requests | $12.00 | |
| **Data Transfer** | 2 TB out to Internet | $180.00 | |
| **WAF** | 1 Web ACL, 20 rules, 10M requests | $20.00 | Rate limiting, IP blocking |
| **Route 53** | 1 hosted zone, 10M queries | $4.00 | |
| **Secrets Manager** | 20 secrets, 1M API calls | $10.00 | |
| **ECR** | 3 repos, 30 images each, 50 GB | $5.00 | Lifecycle: keep 30, expire untagged 7d |
| **VPC/NAT Gateway** | 3 NAT Gateways (multi-AZ) | $135.00 | 3 AZs × 730 hrs + data processing |
| **Total Production** | | **~$2,512/mo** | **~$1,250/mo with Fargate Spot** |

---

## Fargate Spot Savings Analysis

### Workers are ideal for Fargate Spot

| Service | On-Demand Cost | Spot Cost (70% off) | Monthly Savings |
|---------|----------------|---------------------|-----------------|
| **Staging Worker** (1 task × 2 vCPU/4GB) | $88.00 | $26.40 | **$61.60 (70%)** |
| **Prod Worker** (3 tasks × 4 vCPU/8GB) | $792.00 | $237.60 | **$554.40 (70%)** |

### Spot Configuration Requirements

```hcl
# In ECS service definition for worker
capacity_provider_strategy {
  capacity_provider = "FARGATE_SPOT"
  weight            = 100
  base              = 0  # Minimum on-demand tasks for stability
}
```

**Caveats:**
- Spot tasks can be interrupted with 2-minute warning
- Workers must be idempotent and handle `SIGTERM` gracefully
- Set `base = 1` in production to keep 1 on-demand task running
- Use `CELERY_TASK_ACKS_LATE=true` and `CELERY_WORKER_PREFETCH_MULTIPLIER=1`

---

## Scaling Projections

### Cost vs. Request Volume

| Monthly Requests | Staging Cost | Production Cost | Prod w/ Spot |
|------------------|--------------|-----------------|--------------|
| 100K | $420 | $1,250 | $980 |
| 1M | $480 | $1,580 | $1,220 |
| 10M | $650 | $2,400 | $1,850 |
| 100M | $1,200 | $4,800 | $3,600 |

**Scaling assumptions:**
- API scales horizontally (CPU > 70%, Memory > 80%)
- Workers scale on queue depth (1 task per 50 pending tasks)
- RDS scales vertically (storage auto-scaling, instance resize during maintenance)
- ElastiCache scales vertically (node type upgrade)
- ALB costs scale logarithmically with request volume

---

## Cost Optimization Recommendations

### Immediate (No Architecture Changes)

1. **Enable Fargate Spot for Workers** — Save ~$550/mo in production
2. **Enable Compute Savings Plans** — 1-year: ~30% off Fargate/EC2; 3-year: ~50%
3. **RDS Reserved Instances** — 1-year: ~30% off; 3-year: ~60%
4. **ElastiCache Reserved Nodes** — 1-year: ~30% off; 3-year: ~60%
5. **S3 Intelligent-Tiering** — Auto-move objects to cheaper tiers

### Medium-term (Architecture Changes)

1. **Move Workers to EC2 Auto Scaling Group** — 60-70% cheaper than Fargate for steady workloads
2. **Use Aurora Serverless v2** — Pay per use for variable database loads
3. **Consolidate Observability** — Use Grafana Cloud or Datadog instead of self-hosted stack
4. **Enable S3 Lifecycle for ECR** — Already configured: keep 30, expire untagged after 7 days

### Long-term

1. **Negotiate Enterprise Discount (EDP)** — 5-15% off all services at $500K+/year commit
2. **Multi-region Active/Active** — Only if RTO/RPO requires it (doubles infra cost)
3. **Kubernetes (EKS) Migration** — Better density, spot fleet management, but operational overhead

---

## Cost Monitoring & Alerts

### Budgets to Configure

```bash
# Monthly budget alert at 80% and 100%
aws budgets create-budget \
  --account-id $ACCOUNT_ID \
  --budget '{
    "BudgetName": "ContextForge-Prod-Monthly",
    "BudgetLimit": {"Amount": "1500", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST",
    "CostFilters": {"Service": ["AmazonECS", "AmazonRDS", "AmazonElastiCache", "AWSELB", "AmazonCloudWatch", "AmazonS3"]}
  }' \
  --notifications-with-subscribers '[...]'
```

### Key Metrics to Watch

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| `EstimatedCharges` | > 80% of budget | Review scaling, check for runaway resources |
| `ECS Service CPU/Memory` | > 80% sustained | Increase min_capacity or instance size |
| `RDS CPUUtilization` | > 70% sustained | Scale instance class or enable read replicas |
| `ElastiCache CPUUtilization` | > 70% sustained | Scale node type or add shards |
| `ALB RequestCount` | Spike > 3x baseline | Check for DDoS, enable WAF rate limiting |

---

## Assumptions & Sources

| Parameter | Value | Source |
|-----------|-------|--------|
| Hours/month | 730 | 365.25 × 24 ÷ 12 |
| Fargate vCPU-hour | $0.04048 | [AWS Fargate Pricing](https://aws.amazon.com/fargate/pricing/) |
| Fargate GB-hour | $0.004445 | [AWS Fargate Pricing](https://aws.amazon.com/fargate/pricing/) |
| Fargate Spot discount | 70% | [AWS Fargate Spot](https://aws.amazon.com/fargate/pricing/) |
| RDS db.t3.medium | $0.068/hr | [RDS Pricing](https://aws.amazon.com/rds/postgresql/pricing/) |
| RDS db.r6g.xlarge | $0.476/hr | [RDS Pricing](https://aws.amazon.com/rds/postgresql/pricing/) |
| ElastiCache cache.t3.micro | $0.020/hr | [ElastiCache Pricing](https://aws.amazon.com/elasticache/pricing/) |
| ElastiCache cache.r6g.xlarge | $0.212/hr | [ElastiCache Pricing](https://aws.amazon.com/elasticache/pricing/) |
| ALB LCU-hour | $0.008 | [ALB Pricing](https://aws.amazon.com/elasticloadbalancing/pricing/) |
| NAT Gateway hour | $0.045 | [NAT Gateway Pricing](https://aws.amazon.com/vpc/pricing/) |
| Data Transfer (out) | $0.09/GB | [Data Transfer Pricing](https://aws.amazon.com/ec2/pricing/on-demand/) |
| CloudWatch Logs ingest | $0.50/GB | [CloudWatch Pricing](https://aws.amazon.com/cloudwatch/pricing/) |
| CloudWatch Logs storage | $0.03/GB | [CloudWatch Pricing](https://aws.amazon.com/cloudwatch/pricing/) |
| S3 Standard storage | $0.023/GB | [S3 Pricing](https://aws.amazon.com/s3/pricing/) |
| WAF Web ACL | $5.00/mo | [WAF Pricing](https://aws.amazon.com/waf/pricing/) |
| Secrets Manager | $0.40/secret/mo | [Secrets Manager Pricing](https://aws.amazon.com/secrets-manager/pricing/) |
| ECR storage | $0.10/GB/mo | [ECR Pricing](https://aws.amazon.com/ecr/pricing/) |

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2024-11-24 | ContextForge Team | Initial cost breakdown |