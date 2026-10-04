"""Game Repository - Gestion de la persistence des parties.

Responsabilité (SRP) : Accès aux données des parties et matches.
- Sauvegarde/chargement état des parties
- Persistence de l'historique
- Pas de logique métier
"""
import json
import os
import pathlib
import errno
import logging
from typing import Optional, Dict, Any


class GameRepository:
    """Repository pour la gestion de la persistence des parties.
    
    Pattern: Repository Pattern
    SOLID: SRP (une seule responsabilité - persistence des parties)
    """
    
    def __init__(self, persistent_dir: str = 'persistent_bots', 
                 games_index_file: str = 'games_index.json'):
        """Initialise le repository avec les chemins de persistence.
        
        Args:
            persistent_dir: Répertoire pour stocker les données persistantes
            games_index_file: Nom du fichier d'index des parties
        """
        self.persistent_dir = persistent_dir
        self.games_index_path = os.path.join(persistent_dir, games_index_file)
        self.logger = logging.getLogger(__name__)
        
        # Créer le répertoire si nécessaire
        try:
            pathlib.Path(persistent_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
    
    def load_games_index(self) -> Dict[str, Any]:
        """Charge l'index des parties depuis le disque."""
        try:
            if os.path.exists(self.games_index_path):
                with open(self.games_index_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            self.logger.exception('Failed to load games index')
        return {}
    
    def save_games_index_entry(self, game_id: str, meta: dict) -> None:
        """Sauvegarde une entrée dans l'index des parties.
        
        Args:
            game_id: Identifiant unique de la partie
            meta: Métadonnées de la partie (referee, bot_paths, etc.)
        """
        idx = self.load_games_index()
        idx[game_id] = meta
        try:
            with open(self.games_index_path, 'w', encoding='utf-8') as f:
                json.dump(idx, f, indent=2)
        except Exception:
            self.logger.exception('Failed to save games index entry')
    
    def get_game_metadata(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les métadonnées d'une partie depuis l'index."""
        idx = self.load_games_index()
        return idx.get(game_id)
    
    def save_bot_file(self, bot_id: str, code: str) -> str:
        """Sauvegarde le code d'un bot dans un fichier.
        
        Args:
            bot_id: Identifiant du bot
            code: Code Python du bot
            
        Returns:
            Chemin absolu du fichier créé
        """
        bot_dir = os.path.join(self.persistent_dir, bot_id)
        pathlib.Path(bot_dir).mkdir(parents=True, exist_ok=True)
        
        bot_file = os.path.join(bot_dir, 'bot.py')
        with open(bot_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        return os.path.abspath(bot_file)
    
    def load_bot_file(self, bot_path: str) -> Optional[str]:
        """Charge le code d'un bot depuis un fichier.
        
        Args:
            bot_path: Chemin vers le fichier du bot
            
        Returns:
            Code du bot ou None si le fichier n'existe pas
        """
        try:
            if os.path.exists(bot_path):
                with open(bot_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception:
            self.logger.exception(f'Failed to load bot file: {bot_path}')
        return None
