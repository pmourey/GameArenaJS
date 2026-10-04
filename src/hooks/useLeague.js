/**
 * useLeague Hook - Gestion de l'état et des données de ligue
 * 
 * Responsabilité (SRP): Logique métier des ligues uniquement
 * Pattern: Custom Hook (React)
 * SOLID: Séparation logique métier / UI, réutilisable
 * 
 * @returns {Object} État et méthodes liées aux ligues
 */

import { useState, useEffect, useCallback } from 'react';
import { leagueApi } from '../services/leagueApi';

export default function useLeague() {
  const [userLeague, setUserLeague] = useState(null);
  const [allLeagues, setAllLeagues] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  /**
   * Récupère les informations de ligue de l'utilisateur connecté
   */
  const fetchUserLeague = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await leagueApi.getUserLeague();
      setUserLeague(data);
      return data;
    } catch (err) {
      if (err.message && (err.message.includes('Authentication') || err.message.includes('401'))) {
        setUserLeague({
          current_league: 'Wood2',
          league_id: 1,
          elo: 0,
          rank: 1,
          total_bots: 1,
          has_bot: false
        });
        return null;
      }
      setError(err.message);
      console.warn('Error fetching user league:', err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Récupère toutes les ligues disponibles
   */
  const fetchAllLeagues = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await leagueApi.getAllLeagues();
      setAllLeagues(data.leagues || []);
      return data.leagues || [];
    } catch (err) {
      setError(err.message);
      console.error('Error fetching all leagues:', err);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Rafraîchit les données de ligue (utile après une partie jouée)
   */
  const refreshUserLeague = useCallback(async () => {
    return fetchUserLeague();
  }, [fetchUserLeague]);

  /**
   * Charge automatiquement les ligues au mount
   */
  useEffect(() => {
    fetchAllLeagues();
  }, [fetchAllLeagues]);

  return {
    // État
    userLeague,
    allLeagues,
    loading,
    error,
    
    // Méthodes
    fetchUserLeague,
    fetchAllLeagues,
    refreshUserLeague
  };
}
