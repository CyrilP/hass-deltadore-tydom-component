#!/bin/bash

# Script pour voir les logs du conteneur Home Assistant

CONTAINER_NAME="ha-dev"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "📋 Logs du conteneur $CONTAINER_NAME (Ctrl+C pour quitter):"
    echo ""
    docker logs -f "$CONTAINER_NAME"
else
    echo "❌ Le conteneur $CONTAINER_NAME n'est pas en cours d'exécution"
    echo "💡 Lancez d'abord: ./tools/ha.sh"
    exit 1
fi

