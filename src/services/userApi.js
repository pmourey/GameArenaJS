/**
 * User API Service - Abstraction des appels API liés aux utilisateurs
 * 
 * Responsabilité (SRP): Communication avec le backend pour les utilisateurs uniquement
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

export const userApi = {
  /**
   * Connexion utilisateur
   */
  async login(username, password) {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ username, password })
    });
    return handleApiError(response);
  },

  /**
   * Inscription utilisateur
   */
  async register(username, email, password) {
    const response = await fetch(`${API_BASE}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ username, email, password })
    });
    return handleApiError(response);
  },

  /**
   * Récupère le profil de l'utilisateur connecté
   */
  async getProfile() {
    const response = await fetch(`${API_BASE}/api/user/profile`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Récupère l'avatar de l'utilisateur connecté
   */
  async getAvatar() {
    const response = await fetch(`${API_BASE}/api/user/avatar`, {
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      }
    });
    return handleApiError(response);
  },

  /**
   * Met à jour l'avatar (prédéfini)
   */
  async updateAvatar(avatarId) {
    const response = await fetch(`${API_BASE}/api/user/avatar`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader()
      },
      body: JSON.stringify({ avatar: avatarId })
    });
    return handleApiError(response);
  },

  /**
   * Upload un avatar personnalisé
   */
  async uploadAvatar(file) {
    const formData = new FormData();
    formData.append('avatar', file);

    const response = await fetch(`${API_BASE}/api/user/avatar/upload`, {
      method: 'POST',
      headers: {
        ...getAuthHeader()
      },
      body: formData
    });
    return handleApiError(response);
  },

  /**
   * Récupère l'image d'avatar de l'utilisateur connecté
   */
  getAvatarImageUrl() {
    const token = localStorage.getItem('authToken');
    return `${API_BASE}/api/user/avatar/image?token=${token}`;
  },

  /**
   * Récupère l'URL de l'image d'avatar d'un utilisateur spécifique
   */
  getUserAvatarImageUrl(userId) {
    const token = localStorage.getItem('authToken');
    return `${API_BASE}/api/user/${userId}/avatar/image?token=${token}`;
  }
};

export default userApi;
