#!/bin/bash
set -e

echo "🎯 Inicializando Apache AGE..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS age;
    LOAD 'age';
    SET search_path = ag_catalog, "\$user", public;
    
    -- Crear grafo de conocimiento de NEXUS
    SELECT create_graph('nexus_knowledge');
    
    -- Configurar usuarios y permisos
    CREATE USER nexus_user WITH PASSWORD '$NEXUS_DB_PASSWORD';
    GRANT ALL PRIVILEGES ON DATABASE "$POSTGRES_DB" TO nexus_user;
    GRANT USAGE ON SCHEMA ag_catalog TO nexus_user;
EOSQL

echo "✅ Apache AGE inicializado correctamente"