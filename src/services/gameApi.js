/**
 * Game API Service - Abstraction des appels API liés aux parties
 * 
 * Responsabilité (SRP): Communication avec le backend pour les parties uniquement
 * Pattern: Service Layer (frontend)
 * SOLID: Séparation entre composants UI et logique réseau
 */

// Utiliser la même config que le reste de l'app (proxy Vite en dev)
import API_BASE_URL from '../config';
const API_BASE = API_BASE_URL;

/**
 * Récupère le token JWT depuis localStorage
 */
const getAuthHeader = () => {
  const token = localStorage.getItem('token') || localStorage.getItem('authToken');
  return token ? { 'Authorization': `Bearer ${token}` } : {};
};

/**
 * Gestion centralisée des erreurs API
 */
const handleApiError = async (response) => {
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Network error' }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }
  return response.json();
};

export const gameApi = {
  /**
   * Liste les referees disponibles
   */
  async getReferees() {
    const response = await fetch(`${API_BASE}/api/referees`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère le template de bot
   */
  async getPlayerTemplate() {
    const response = await fetch(`${API_BASE}/api/template`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Crée une nouvelle partie
   * 
   * @param {Object} params - Paramètres de la partie
   * @param {string} params.referee - Nom du referee ('pacman')
   * @param {string} params.mode - Mode de jeu ('player-vs-bot' ou 'bot-vs-bot')
   * @param {string} [params.player_code] - Code du joueur (mode player-vs-bot)
   * @param {number} [params.player_bot_id] - ID du bot joueur
   * @param {string} [params.opponent] - Adversaire (mode player-vs-bot)
   * @param {string} [params.bot1] - Premier bot (mode bot-vs-bot)
   * @param {string} [params.bot2] - Second bot (mode bot-vs-bot)
   * @param {string} [params.bot_runner] - Type de runner ('auto', 'docker', 'subprocess')
   */
  async createGame(params) {
    const response = await fetch(`${API_BASE}/api/games`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      },
      body: JSON.stringify(params)
    });
    return handleApiError(response);
  },

  /**
   * Récupère les informations d'une partie
   */
  async getGame(gameId) {
    const response = await fetch(`${API_BASE}/api/games/${gameId}`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Exécute un tour de jeu
   */
  async stepGame(gameId) {
    const response = await fetch(`${API_BASE}/api/games/${gameId}/step`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère l'historique complet d'une partie
   */
  async getGameHistory(gameId) {
    const response = await fetch(`${API_BASE}/api/games/${gameId}/history`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère les logs de debug du runner Docker
   */
  async getRunnerDebug() {
    const response = await fetch(`${API_BASE}/api/debug/runner`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  }
};

export default gameApi;
