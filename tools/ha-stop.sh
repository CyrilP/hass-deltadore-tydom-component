#!/bin/bash

# Script pour arrêter le conteneur Home Assistant de développement

CONTAINER_NAME="ha-dev"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "🛑 Arrêt du conteneur $CONTAINER_NAME..."
    docker stop "$CONTAINER_NAME"
    echo "✅ Conteneur arrêté"
elif docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "🗑️  Suppression du conteneur arrêté $CONTAINER_NAME..."
    docker rm "$CONTAINER_NAME"
    echo "✅ Conteneur supprimé"
else
    echo "ℹ️  Aucun conteneur $CONTAINER_NAME trouvé"
fi

