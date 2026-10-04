/**
 * Bot API Service - Abstraction des appels API liés aux bots
 * 
 * Responsabilité (SRP): Communication avec le backend pour les bots uniquement
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

export const botApi = {
  /**
   * Récupère tous les bots de l'utilisateur
   */
  async getUserBots() {
    const response = await fetch(`${API_BASE}/api/bots/my`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère tous les bots actifs (pour sélection adversaire)
   */
  async getAllBots() {
    const response = await fetch(`${API_BASE}/api/bots?all=true`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère un bot spécifique par ID
   */
  async getBot(botId) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Crée un nouveau bot
   */
  async createBot(name, code = '') {
    const response = await fetch(`${API_BASE}/api/bots`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      },
      body: JSON.stringify({ name, code })
    });
    return handleApiError(response);
  },

  /**
   * Sauvegarde le code d'un bot (draft)
   */
  async saveBot(botId, code) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/save`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      },
      body: JSON.stringify({ code })
    });
    return handleApiError(response);
  },

  /**
   * Soumet un bot à l'arène (crée une version)
   */
  async submitToArena(botId) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/submit-to-arena`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère les versions d'un bot
   */
  async getBotVersions(botId) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/versions`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère une version spécifique d'un bot
   */
  async getBotVersion(botId, versionNumber) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/versions/${versionNumber}`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Charge une version spécifique dans l'éditeur
   */
  async loadBotVersion(botId, versionNumber) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/load-version/${versionNumber}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Rollback vers une version antérieure
   */
  async rollbackBot(botId, versionNumber) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/rollback/${versionNumber}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Désactive un bot de l'arène
   */
  async deactivateBot(botId) {
    const response = await fetch(`${API_BASE}/api/bots/${botId}/deactivate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  }
};

export default botApi;
