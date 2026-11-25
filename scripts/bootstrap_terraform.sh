#!/usr/bin/env bash
# =============================================================================
# ContextForge Terraform Bootstrap Script
# Sets up S3 backend bucket, DynamoDB lock table, and runs terraform init
# for staging/prod environments
#
# Usage:
#   ./scripts/bootstrap_terraform.sh <environment> [aws_region]
#
# Examples:
#   ./scripts/bootstrap_terraform.sh staging us-east-1
#   ./scripts/bootstrap_terraform.sh prod us-east-1
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TERRAFORM_DIR="$PROJECT_ROOT/infra/terraform"

# Default values
ENVIRONMENT="${1:-}"
AWS_REGION="${2:-us-east-1}"
PROJECT_NAME="contextforge"

# Validate inputs
if [[ -z "$ENVIRONMENT" ]]; then
  echo -e "${RED}Error: Environment is required${NC}"
  echo "Usage: $0 <environment> [aws_region]"
  echo "Environments: staging, prod"
  exit 1
fi

if [[ ! "$ENVIRONMENT" =~ ^(staging|prod)$ ]]; then
  echo -e "${RED}Error: Invalid environment '$ENVIRONMENT'. Must be 'staging' or 'prod'${NC}"
  exit 1
fi

# Derived names
TF_STATE_BUCKET="${PROJECT_NAME}-tfstate-${ENVIRONMENT}-${AWS_REGION}"
TF_STATE_LOCK_TABLE="${PROJECT_NAME}-tfstate-lock-${ENVIRONMENT}"
TF_STATE_KEY="${PROJECT_NAME}/${ENVIRONMENT}/terraform.tfstate"

echo -e "${BLUE}==============================================================================${NC}"
echo -e "${BLUE}ContextForge Terraform Bootstrap${NC}"
echo -e "${BLUE}==============================================================================${NC}"
echo -e "Environment:     ${GREEN}$ENVIRONMENT${NC}"
echo -e "AWS Region:      ${GREEN}$AWS_REGION${NC}"
echo -e "State Bucket:    ${GREEN}$TF_STATE_BUCKET${NC}"
echo -e "Lock Table:      ${GREEN}$TF_STATE_LOCK_TABLE${NC}"
echo -e "State Key:       ${GREEN}$TF_STATE_KEY${NC}"
echo -e "${BLUE}==============================================================================${NC}"

# Check AWS CLI is installed and configured
if ! command -v aws &> /dev/null; then
  echo -e "${RED}Error: AWS CLI not found. Please install and configure it.${NC}"
  exit 1
fi

# Verify AWS credentials
echo -e "\n${YELLOW}Verifying AWS credentials...${NC}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)
if [[ -z "$AWS_ACCOUNT_ID" ]]; then
  echo -e "${RED}Error: AWS credentials not configured or invalid${NC}"
  exit 1
fi
echo -e "AWS Account ID: ${GREEN}$AWS_ACCOUNT_ID${NC}"

# Check if bucket exists
echo -e "\n${YELLOW}Checking S3 backend bucket...${NC}"
if aws s3api head-bucket --bucket "$TF_STATE_BUCKET" 2>/dev/null; then
  echo -e "Bucket ${GREEN}$TF_STATE_BUCKET${NC} already exists"
else
  echo -e "Creating bucket ${GREEN}$TF_STATE_BUCKET${NC}..."
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION"
  else
    aws s3api create-bucket \
      --bucket "$TF_STATE_BUCKET" \
      --region "$AWS_REGION" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION"
  fi

  # Enable versioning
  aws s3api put-bucket-versioning \
    --bucket "$TF_STATE_BUCKET" \
    --versioning-configuration Status=Enabled

  # Enable server-side encryption
  aws s3api put-bucket-encryption \
    --bucket "$TF_STATE_BUCKET" \
    --server-side-encryption-configuration '{
      "Rules": [{
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        }
      }]
    }'

  # Block public access
  aws s3api put-public-access-block \
    --bucket "$TF_STATE_BUCKET" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

  # Add bucket policy to enforce SSL
  aws s3api put-bucket-policy \
    --bucket "$TF_STATE_BUCKET" \
    --policy "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Sid\": \"DenyInsecureConnections\",
        \"Effect\": \"Deny\",
        \"Principal\": \"*\",
        \"Action\": \"s3:*\",
        \"Resource\": [
          \"arn:aws:s3:::$TF_STATE_BUCKET\",
          \"arn:aws:s3:::$TF_STATE_BUCKET/*\"
        ],
        \"Condition\": {
          \"Bool\": {
            \"aws:SecureTransport\": \"false\"
          }
        }
      }]
    }"

  echo -e "${GREEN}Bucket created and configured successfully${NC}"
fi

# Check if DynamoDB table exists
echo -e "\n${YELLOW}Checking DynamoDB lock table...${NC}"
if aws dynamodb describe-table --table-name "$TF_STATE_LOCK_TABLE" --region "$AWS_REGION" 2>/dev/null | grep -q "ACTIVE"; then
  echo -e "Table ${GREEN}$TF_STATE_LOCK_TABLE${NC} already exists and is active"
else
  echo -e "Creating DynamoDB table ${GREEN}$TF_STATE_LOCK_TABLE${NC}..."
  aws dynamodb create-table \
    --table-name "$TF_STATE_LOCK_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$AWS_REGION" \
    --tags Key=Project,Value="$PROJECT_NAME" Key=Environment,Value="$ENVIRONMENT"

  # Wait for table to be active
  echo -e "Waiting for table to become active..."
  aws dynamodb wait table-exists --table-name "$TF_STATE_LOCK_TABLE" --region "$AWS_REGION"
  echo -e "${GREEN}Table created successfully${NC}"
fi

# Create backend configuration file
echo -e "\n${YELLOW}Creating Terraform backend configuration...${NC}"
BACKEND_CONFIG_FILE="$TERRAFORM_DIR/backend-${ENVIRONMENT}.hcl"
cat > "$BACKEND_CONFIG_FILE" <<EOF
# Terraform Backend Configuration for $ENVIRONMENT
# Generated by bootstrap_terraform.sh on $(date -u +"%Y-%m-%d %H:%M:%S UTC")

bucket         = "$TF_STATE_BUCKET"
key            = "$TF_STATE_KEY"
region         = "$AWS_REGION"
dynamodb_table = "$TF_STATE_LOCK_TABLE"
encrypt        = true
EOF

echo -e "Backend config written to: ${GREEN}$BACKEND_CONFIG_FILE${NC}"

# Initialize Terraform
echo -e "\n${YELLOW}Initializing Terraform...${NC}"
cd "$TERRAFORM_DIR"

terraform init \
  -backend-config="$BACKEND_CONFIG_FILE" \
  -upgrade

echo -e "\n${GREEN}==============================================================================${NC}"
echo -e "${GREEN}Bootstrap Complete!${NC}"
echo -e "${GREEN}==============================================================================${NC}"
echo -e "Environment:     ${GREEN}$ENVIRONMENT${NC}"
echo -e "State Bucket:    ${GREEN}$TF_STATE_BUCKET${NC}"
echo -e "Lock Table:      ${GREEN}$TF_STATE_LOCK_TABLE${NC}"
echo -e ""
echo -e "Next steps:"
echo -e "  1. Review the backend config: ${BLUE}$BACKEND_CONFIG_FILE${NC}"
echo -e "  2. Run terraform plan: ${BLUE}terraform plan -var=\"environment=$ENVIRONMENT\" -var=\"aws_region=$AWS_REGION\"${NC}"
echo -e "  3. Run terraform apply: ${BLUE}terraform apply -var=\"environment=$ENVIRONMENT\" -var=\"aws_region=$AWS_REGION\"${NC}"
echo -e "${GREEN}==============================================================================${NC}"