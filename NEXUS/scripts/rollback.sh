#!/bin/bash
set -e

function rollback_deployment() {
    local deployment=$1
    local namespace=$2
    
    echo "Rolling back deployment $deployment in namespace $namespace"
    
    # Get current revision
    local current_revision=$(kubectl rollout history deployment/$deployment -n $namespace \
        --tail=1 | awk 'NR==2{print $1}')
    
    # Get previous revision
    local previous_revision=$(kubectl rollout history deployment/$deployment -n $namespace \
        | awk 'NR==3{print $1}')
    
    if [ -z "$previous_revision" ]; then
        echo "No previous revision found. Cannot rollback."
        return 1
    fi
    
    # Perform rollback
    kubectl rollout undo deployment/$deployment -n $namespace \
        --to-revision=$previous_revision
    
    # Wait for rollback to complete
    kubectl rollout status deployment/$deployment -n $namespace \
        --timeout=300s
    
    echo "Rollback completed. Current revision: $previous_revision"
}

function emergency_rollback() {
    echo "🚨 Initiating emergency rollback"
    
    # Rollback core services
    rollback_deployment "nexus-core" "nexus"
    rollback_deployment "nexus-api" "nexus"
    rollback_deployment "nexus-dashboard" "nexus"
    
    # Scale down problematic services if needed
    kubectl scale deployment/nexus-worker --replicas=0 -n nexus
    
    # Restore database from backup if necessary
    if [ "$RESTORE_DB" == "true" ]; then
        restore_database_backup
    fi
    
    echo "✅ Emergency rollback completed"
}

function restore_database_backup() {
    local backup_file=$(find /backups -name "nexus-backup-*.sql" -mtime -1 | sort -r | head -1)
    
    if [ -z "$backup_file" ]; then
        echo "No recent backup found"
        return 1
    fi
    
    echo "Restoring database from backup: $backup_file"
    
    # Stop services that use database
    kubectl scale deployment/nexus-core --replicas=0 -n nexus
    kubectl scale deployment/nexus-api --replicas=0 -n nexus
    
    # Restore backup
    kubectl exec -n nexus deployment/nexus-db -- \
        psql -U $DB_USER -d $DB_NAME -f /backups/$backup_file
    
    # Restart services
    kubectl scale deployment/nexus-core --replicas=3 -n nexus
    kubectl scale deployment/nexus-api --replicas=2 -n nexus
    
    echo "Database restore completed"
}

# Main rollback logic
case "${1:-}" in
    "emergency")
        emergency_rollback
        ;;
    "deployment")
        rollback_deployment "$2" "$3"
        ;;
    "database")
        RESTORE_DB=true
        emergency_rollback
        ;;
    *)
        echo "Usage: $0 [emergency|deployment|database]"
        exit 1
        ;;
esac