#!/bin/bash
# Script de déploiement GameArena (LOCAL uniquement)
# Usage: ./deploy.sh [dev|prod]

set -e  # Exit on error

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV="${1:-dev}"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"

# ============================================
# Fonctions utilitaires
# ============================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================
# Validation de l'environnement
# ============================================

if [ "$ENV" != "dev" ] && [ "$ENV" != "prod" ]; then
    log_error "Environnement invalide: $ENV. Utilisez 'dev' ou 'prod'"
    exit 1
fi

log_info "Déploiement en environnement: ${ENV}"

# ============================================
# Vérification des prérequis
# ============================================

log_info "Vérification des prérequis..."

# Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker n'est pas installé"
    exit 1
fi
log_success "Docker: $(docker --version)"

# Docker Compose
if ! docker compose version &> /dev/null; then
    log_error "Docker Compose n'est pas installé"
    exit 1
fi
log_success "Docker Compose: OK"

# Vérifier que Docker daemon tourne
if ! docker ps &> /dev/null; then
    log_error "Docker daemon n'est pas démarré"
    exit 1
fi
log_success "Docker daemon: Running"

# ============================================
# Configuration de l'environnement
# ============================================

# Copier .env.example si .env n'existe pas
if [ ! -f "$ENV_FILE" ]; then
    if [ -f ".env.docker.example" ]; then
        log_warning "Fichier .env manquant, copie depuis .env.docker.example"
        cp .env.docker.example "$ENV_FILE"
        log_warning "⚠️  IMPORTANT: Éditez .env et changez les secrets avant de lancer en production!"
    else
        log_error "Fichier .env.docker.example manquant"
        exit 1
    fi
fi

# Vérifier que les secrets ont été changés en prod
if [ "$ENV" = "prod" ]; then
    if grep -q "change-this-secret-key-in-production" "$ENV_FILE" 2>/dev/null; then
        log_error "⚠️  SÉCURITÉ: Les secrets par défaut sont toujours dans .env!"
        log_error "Éditez .env et changez SECRET_KEY et JWT_SECRET_KEY avant de déployer en production"
        exit 1
    fi
    log_success "Secrets de production configurés"
fi

# ============================================
# Build et démarrage des conteneurs
# ============================================

log_info "Arrêt des conteneurs existants..."
docker compose -f "$COMPOSE_FILE" down || true

log_info "Construction de l'image Docker..."
docker compose -f "$COMPOSE_FILE" build

# Build l'image bot (pour exécution des bots en Docker)
if [ -f "runner/build_bot_image.sh" ]; then
    log_info "Construction de l'image gamearena-bot..."
    bash runner/build_bot_image.sh
    log_success "Image gamearena-bot construite"
fi

log_info "Démarrage des conteneurs..."
if [ "$ENV" = "dev" ]; then
    # En dev: logs interactifs
    docker compose -f "$COMPOSE_FILE" up
else
    # En prod: détaché
    docker compose -f "$COMPOSE_FILE" up -d
    
    # Attendre que le service soit prêt
    log_info "Attente du démarrage du service..."
    sleep 5
    
    log_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_success "✅ GameArena déployé avec succès!"
    log_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    log_info "🌐 URL: http://localhost:5000"
    log_info "📊 API: http://localhost:5000/api/referees"
    echo ""
    log_info "Commandes utiles:"
    echo "  - Voir les logs:        docker compose logs -f"
    echo "  - Arrêter:              docker compose down"
    echo "  - Redémarrer:           docker compose restart"
    echo "  - Reconstruire:         docker compose build --no-cache"
    echo "  - Shell dans container: docker compose exec gamearena bash"
    echo ""
    log_info "Conteneurs en cours d'exécution:"
    docker compose -f "$COMPOSE_FILE" ps
fi
