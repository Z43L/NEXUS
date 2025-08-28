#!/bin/bash
set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Variables de entorno
ENVIRONMENT=${1:-production}
REGION=${2:-us-west-2}
ACTION=${3:-apply}

function log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

function log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

function log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

function log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

function check_dependencies() {
    local deps=("terraform" "kubectl" "helm" "aws" "jq")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            log_error "Dependency $dep not found. Please install it."
            exit 1
        fi
    done
    log_info "All dependencies are installed"
}

function setup_aws_credentials() {
    if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
        log_error "AWS credentials not set. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
        exit 1
    fi
    log_info "AWS credentials configured"
}

function terraform_deploy() {
    local env=$1
    local action=$2
    
    log_info "Running Terraform $action for $env environment"
    
    cd infra/aws
    
    terraform init -reconfigure \
        -backend-config="key=$env/terraform.tfstate" \
        -backend-config="bucket=nexus-terraform-state" \
        -backend-config="region=$REGION"
    
    if [ "$action" == "apply" ]; then
        terraform apply -auto-approve \
            -var="environment=$env" \
            -var="aws_region=$REGION" \
            -var="db_username=$DB_USERNAME" \
            -var="db_password=$DB_PASSWORD" \
            -var="openai_api_key=$OPENAI_API_KEY"
    elif [ "$action" == "destroy" ]; then
        terraform destroy -auto-approve \
            -var="environment=$env" \
            -var="aws_region=$REGION"
    else:
        terraform plan \
            -var="environment=$env" \
            -var="aws_region=$REGION" \
            -var="db_username=$DB_USERNAME" \
            -var="db_password=$DB_PASSWORD" \
            -var="openai_api_key=$OPENAI_API_KEY"
    fi
    
    cd - > /dev/null
}

function kubernetes_deploy() {
    local env=$1
    
    log_info "Deploying to Kubernetes cluster"
    
    # Update kubeconfig
    aws eks update-kubeconfig --name nexus-$env --region $REGION
    
    # Create namespace if not exists
    kubectl get namespace nexus || kubectl create namespace nexus
    
    # Deploy with Helm
    helm upgrade --install nexus ./charts/nexus \
        --namespace nexus \
        --values ./charts/nexus/values-$env.yaml \
        --set image.tag=$(git rev-parse --short HEAD) \
        --atomic \
        --timeout 15m
    
    # Wait for deployments to be ready
    kubectl wait --for=condition=available deployment/nexus-core \
        --namespace nexus \
        --timeout=300s
    
    log_info "Running post-deployment checks"
    ./scripts/health-check.sh
}

function main() {
    log_info "Starting NEXUS infrastructure deployment"
    log_info "Environment: $ENVIRONMENT"
    log_info "Region: $REGION"
    log_info "Action: $ACTION"
    
    # Check dependencies
    check_dependencies
    
    # Setup AWS credentials
    setup_aws_credentials
    
    # Terraform deployment
    terraform_deploy "$ENVIRONMENT" "$ACTION"
    
    if [ "$ACTION" == "apply" ]; then
        # Kubernetes deployment
        kubernetes_deploy "$ENVIRONMENT"
        
        log_success "NEXUS infrastructure deployed successfully!"
        log_info "Dashboard URL: https://dashboard.$ENVIRONMENT.nexus.ai"
        log_info "API URL: https://api.$ENVIRONMENT.nexus.ai"
    fi
}

# Run main function
main "$@"