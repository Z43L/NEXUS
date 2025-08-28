#!/bin/bash
# Script de despliegue para Fase 1: Núcleo Fundamental

set -e
echo "🚀 Iniciando Fase 1: Núcleo Fundamental"

# 1. Configurar red blockchain inicial
echo "⛓️  Desplegando blockchain testnet..."
./deploy_blockchain.sh --nodes 5 --consensus proof-of-knowledge --env testnet

# 2. Inicializar sistema de memoria distribuida
echo "💾 Configurando memoria vectorial..."
./setup_memory_layer.sh --shards 3 --replicas 2 --backend weaviate

# 3. Desplegar agente razonador básico
echo "🤖 Implementando agente razonador..."
./deploy_reasoning_agent.sh --model llama3-70b --tools basic

# 4. Configurar monitorización básica
echo "📊 Configurando sistema de monitorización..."
./setup_monitoring.sh --stack prometheus-grafana --alerting basic

echo "✅ Fase 1 completada exitosamente!"