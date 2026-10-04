# GameArena - Multi-stage Dockerfile
# Build frontend + Run Flask backend

# ============================================
# Stage 1: Build Frontend (Node.js)
# ============================================
FROM node:18-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy package files
COPY frontend/package*.json ./

# Install ALL dependencies (including devDependencies needed for build)
RUN npm ci

# Copy frontend source
COPY frontend/ ./

# Build frontend (production mode)
# Note: VITE_API_BASE_URL sera vide pour utiliser même origine
ENV VITE_API_BASE_URL=
RUN npm run build

# ============================================
# Stage 2: Python Runtime
# ============================================
FROM python:3.11-slim

# Métadonnées
LABEL maintainer="GameArena Team"
LABEL description="GameArena - Bot Arena Prototype with Flask + React"
LABEL version="1.0.0"

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=app.py \
    FLASK_ENV=production \
    PORT=5000

# Installer dépendances système
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Créer utilisateur non-root pour sécurité
RUN useradd -m -u 1000 gamearena && \
    mkdir -p /app && \
    chown -R gamearena:gamearena /app

WORKDIR /app

# Copier requirements et installer dépendances Python
COPY --chown=gamearena:gamearena requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code backend
COPY --chown=gamearena:gamearena app.py .
COPY --chown=gamearena:gamearena game_sdk.py .
COPY --chown=gamearena:gamearena models.py .
COPY --chown=gamearena:gamearena auth.py .
COPY --chown=gamearena:gamearena arena.py .
COPY --chown=gamearena:gamearena boss_system.py .
COPY --chown=gamearena:gamearena leagues.py .
COPY --chown=gamearena:gamearena referees/ ./referees/
COPY --chown=gamearena:gamearena runner/ ./runner/
COPY --chown=gamearena:gamearena services/ ./services/
COPY --chown=gamearena:gamearena repositories/ ./repositories/
COPY --chown=gamearena:gamearena bots/ ./bots/

# Copier le frontend buildé depuis le stage 1
COPY --from=frontend-builder --chown=gamearena:gamearena /app/frontend/dist ./static

# Créer les répertoires nécessaires
RUN mkdir -p persistent_bots instance && \
    chown -R gamearena:gamearena persistent_bots instance

# Copier la base de données existante si elle existe (sera écrasée par volume en prod)
# Note: Le COPY échouera silencieusement si le fichier n'existe pas
COPY --chown=gamearena:gamearena instance/ ./instance/ 

# Changer vers utilisateur non-root
USER gamearena

# Exposer le port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/referees || exit 1

# Commande de démarrage
CMD ["python3", "app.py"]
