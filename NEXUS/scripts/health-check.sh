#!/bin/bash
set -e

# Variables
NAMESPACE="nexus"
TIMEOUT=300
INTERVAL=10

function check_pod_status() {
    local pod=$1
    local status=$(kubectl get pod $pod -n $NAMESPACE -o jsonpath='{.status.phase}')
    if [ "$status" != "Running" ]; then
        echo "Pod $pod is not running. Status: $status"
        return 1
    fi
    return 0
}

function check_service_endpoints() {
    local service=$1
    local port=$2
    local endpoint=$(kubectl get svc $service -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
    
    if [ -z "$endpoint" ]; then
        echo "Service $service has no endpoint"
        return 1
    fi
    
    # Test connectivity
    if ! nc -z -w5 $endpoint $port; then
        echo "Cannot connect to $service on $endpoint:$port"
        return 1
    fi
    
    return 0
}

function check_web_service() {
    local url=$1
    local expected_status=${2:-200}
    
    local status_code=$(curl -s -o /dev/null -w "%{http_code}" $url)
    
    if [ "$status_code" -ne "$expected_status" ]; then
        echo "HTTP check failed for $url. Expected: $expected_status, Got: $status_code"
        return 1
    fi
    
    return 0
}

function run_health_checks() {
    echo "Running health checks..."
    
    # Check core services
    services=(
        "nexus-core:8000"
        "nexus-api:3000"
        "nexus-dashboard:80"
    )
    
    for service in "${services[@]}"; do
        IFS=':' read -r svc port <<< "$service"
        if ! check_service_endpoints $svc $port; then
            return 1
        fi
    done
    
    # Check database connectivity
    echo "Checking database connectivity..."
    kubectl exec -n $NAMESPACE deployment/nexus-core -- \
        pg_isready -h $DB_HOST -p 5432 -U $DB_USER
    
    # Check Redis connectivity
    echo "Checking Redis connectivity..."
    kubectl exec -n $NAMESPACE deployment/nexus-core -- \
        redis-cli -h $REDIS_HOST ping
    
    # Check Weaviate health
    echo "Checking Weaviate health..."
    WEAVIATE_URL=$(kubectl get svc weaviate -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
    check_web_service "http://$WEAVIATE_URL:8080/v1/.well-known/ready" 200
    
    # Check blockchain nodes
    echo "Checking blockchain nodes..."
    for i in {0..6}; do
        check_pod_status "nexus-blockchain-node-$i"
    done
    
    echo "All health checks passed!"
    return 0
}

# Wait for pods to be ready
echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=nexus \
    --namespace $NAMESPACE \
    --timeout=${TIMEOUT}s

# Run health checks
if run_health_checks; then
    echo "✅ All systems operational"
    exit 0
else:
    echo "❌ Health checks failed"
    exit 1
fi