#!/bin/bash
set -e

echo "🚀 Iniciando despliegue de la blockchain NEXUS..."

# Variables de configuración
NETWORK_TYPE="${1:-testnet}"
NODE_COUNT="${2:-5}"
VALIDATOR_COUNT="${3:-3}"

# Configuración específica por tipo de red
case $NETWORK_TYPE in
    "testnet")
        CHAIN_SPEC="nexus-testnet"
        BOOTNODES=("enode://node1@testnet.nexus.ai:30333" "enode://node2@testnet.nexus.ai:30333")
        ;;
    "mainnet")
        CHAIN_SPEC="nexus-mainnet"
        BOOTNODES=("enode://mainnet-node1@nexus.ai:30333" "enode://mainnet-node2@nexus.ai:30333")
        ;;
    *)
        echo "Tipo de red no válido: $NETWORK_TYPE"
        exit 1
        ;;
esac

# Crear directorios de datos
echo "📁 Creando directorios de datos..."
for i in $(seq 1 $NODE_COUNT); do
    mkdir -p /data/nexus/chaindata/node$i
    mkdir -p /data/nexus/keystore/node$i
done

# Configurar y desplegar nodos
echo "🔄 Configurando $NODE_COUNT nodos..."
for i in $(seq 1 $NODE_COUNT); do
    echo "🛠️  Configurando nodo $i..."
    
    # Generar claves para validadores
    if [ $i -le $VALIDATOR_COUNT ]; then
        ./nexus-node key generate --scheme sr25519 --output /data/nexus/keystore/node$i/validator.key
    fi
    
    # Configurar archivo de configuración del nodo
    cat > /data/nexus/config/node$i.toml << EOF
[name]
node = "nexus-node-$i"

[chain]
spec = "$CHAIN_SPEC"
base_path = "/data/nexus/chaindata/node$i"

[network]
bootnodes = ${BOOTNODES[@]}
port = $((30333 + i))

[telemetry]
url = "wss://telemetry.nexus.ai:8000/submit"

[consensus]
validator = $([ $i -le $VALIDATOR_COUNT ] && echo "true" || echo "false")
EOF
done

# Iniciar servicios de nodos
echo "🔄 Iniciando servicios de nodos..."
for i in $(seq 1 $NODE_COUNT); do
    systemctl enable nexus-node-$i
    systemctl start nexus-node-$i
    echo "✅ Nodo $i iniciado"
done

echo "🎉 Despliegue de blockchain completado!"