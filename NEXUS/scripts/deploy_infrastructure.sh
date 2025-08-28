#!/bin/bash

# Script de despliegue de infraestructura inicial
set -e

echo "🚀 Iniciando despliegue de la infraestructura NEXUS..."

# 1. Desplegar nodos blockchain
echo "📦 Desplegando nodos blockchain..."
./deploy_blockchain_nodes.sh --count 5 --network testnet

# 2. Configurar base de datos distribuida
echo "🗄️ Configurando base de datos vectorial..."
./setup_vector_db.sh --shards 3 --replicas 1

# 3. Inicializar grafos de conocimiento
echo "🧠 Inicializando grafos de conocimiento..."
./init_knowledge_graphs.sh --graphs core_knowledge domain_knowledge

# 4. Configurar red P2P
echo "🌐 Configurando red P2P..."
./setup_p2p_network.sh --peers 50 --protocol libp2p

echo "✅ Infraestructura desplegada exitosamente!"