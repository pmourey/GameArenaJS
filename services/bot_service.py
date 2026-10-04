"""Bot Service - Logique métier des bots.

Responsabilité (SRP) : Gestion métier des bots uniquement.
- Validation du code bot
- Gestion des versions
- Orchestration création/mise à jour
- PAS d'accès direct DB (utilise BotRepository)
"""
import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from repositories.bot_repository import BotRepository
from repositories.game_repository import GameRepository


class BotService:
    """Service pour la gestion métier des bots.
    
    Pattern: Service Layer
    SOLID: 
        - SRP (logique métier bots uniquement)
        - DIP (dépend de BotRepository abstrait, pas de SQLAlchemy)
        - OCP (extensible via héritage)
    """
    
    # Validation regex for bot actions
    ACTION_RE = re.compile(r'^(MOVE\s+-?\d+\s+-?\d+(?:\s+-?\d+)?)$', re.IGNORECASE)
    
    def __init__(self, bot_repository: BotRepository = None, 
                 game_repository: GameRepository = None):
        """Initialise le service avec dependency injection.
        
        Args:
            bot_repository: Repository pour accès données bots (DIP)
            game_repository: Repository pour persistence fichiers bots
        """
        self.bot_repo = bot_repository or BotRepository()
        self.game_repo = game_repository or GameRepository()
        self.logger = logging.getLogger(__name__)
    
    def validate_action_format(self, raw_output: str, 
                               normalized_action: str) -> Tuple[str, str]:
        """Valide le format d'une action de bot.
        
        Args:
            raw_output: Sortie brute du bot
            normalized_action: Action normalisée
            
        Returns:
            Tuple (action, error_message)
        """
        # Check if bot produced no output
        if not raw_output or not raw_output.strip():
            return normalized_action, 'no output from bot'
        
        first_line = ''
        for ln in raw_output.splitlines():
            if ln and ln.strip():
                first_line = ln.strip()
                break
        
        if not first_line:
            return normalized_action, 'no valid output from bot'
        
        if self.ACTION_RE.match(first_line):
            return normalized_action, ''
        
        return normalized_action, f'invalid action format: "{first_line}"'
    
    def validate_bot_code(self, code: str) -> Tuple[bool, str]:
        """Valide le code Python d'un bot.
        
        Args:
            code: Code Python à valider
            
        Returns:
            Tuple (is_valid, error_message)
        """
        if not code or not code.strip():
            return False, "Bot code cannot be empty"
        
        # Vérification syntaxe Python basique
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            return False, f"Syntax error: {e}"
        
        # Validations de sécurité supplémentaires pourraient être ajoutées ici
        # Ex: interdire imports dangereux, etc.
        
        return True, ""
    
    def create_bot(self, user_id: int, name: str, code: str = '', 
                   referee_type: str = 'pacman') -> Dict[str, Any]:
        """Crée un nouveau bot avec validation.
        
        Args:
            user_id: ID de l'utilisateur propriétaire
            name: Nom du bot
            code: Code Python du bot (draft initial)
            referee_type: Type de referee (défaut: pacman)
            
        Returns:
            Dictionnaire avec les informations du bot créé
            
        Raises:
            ValueError: Si la validation échoue
        """
        # Validation
        if not name or not name.strip():
            raise ValueError("Bot name is required")
        
        # Validation code optionnelle (peut être vide au départ)
        if code and code.strip():
            is_valid, error = self.validate_bot_code(code)
            if not is_valid:
                raise ValueError(f"Invalid bot code: {error}")
        
        # Création via repository
        bot = self.bot_repo.create(
            user_id=user_id,
            name=name.strip(),
            referee_type=referee_type,
            code=code
        )
        
        self.logger.info(f"Created bot {bot.id} for user {user_id}")
        
        return {
            'id': bot.id,
            'name': bot.name,
            'referee_type': bot.referee_type,
            'code': bot.code,
            'latest_version_number': bot.latest_version_number,
            'created_at': bot.created_at.isoformat()
        }
    
    def save_bot_code(self, bot_id: int, code: str, user_id: int = None) -> Dict[str, Any]:
        """Sauvegarde le code d'un bot sans créer de version (Playground draft).
        
        Args:
            bot_id: ID du bot
            code: Nouveau code
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Informations du bot mis à jour
            
        Raises:
            ValueError: Si validation échoue ou bot introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        # Vérification propriété
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        # Validation (permissive pour Playground)
        if code:  # Permet code vide pour draft
            is_valid, error = self.validate_bot_code(code)
            if not is_valid:
                self.logger.warning(f"Bot {bot_id} saved with invalid code: {error}")
        
        # Mise à jour du code draft (pas de version)
        bot.code = code
        self.bot_repo.save(bot)
        
        self.logger.info(f"Saved draft code for bot {bot_id}")
        
        return {
            'id': bot.id,
            'name': bot.name,
            'code': bot.code,
            'latest_version_number': bot.latest_version_number,
            'updated_at': bot.updated_at.isoformat() if bot.updated_at else None
        }
    
    def update_bot_code(self, bot_id: int, code: str, user_id: int = None) -> Dict[str, Any]:
        """Met à jour le code d'un bot (crée une nouvelle version).
        
        Args:
            bot_id: ID du bot
            code: Nouveau code
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Informations de la nouvelle version
            
        Raises:
            ValueError: Si validation échoue
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        # Vérification propriété
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        # Validation
        is_valid, error = self.validate_bot_code(code)
        if not is_valid:
            raise ValueError(f"Invalid bot code: {error}")
        
        # Création nouvelle version
        version = self.bot_repo.create_version(bot_id, code)
        
        self.logger.info(f"Updated bot {bot_id} to version {version.version_number}")
        
        return {
            'bot_id': bot_id,
            'version_number': version.version_number,
            'created_at': version.created_at.isoformat()
        }
    
    def get_bot_code(self, bot_id: int, version: int = None) -> Optional[str]:
        """Récupère le code d'un bot (dernière version ou version spécifique).
        
        Args:
            bot_id: ID du bot
            version: Numéro de version (None = dernière version)
            
        Returns:
            Code du bot ou None si introuvable
        """
        if version:
            bot_version = self.bot_repo.get_version(bot_id, version)
        else:
            bot_version = self.bot_repo.get_latest_version(bot_id)
        
        return bot_version.code if bot_version else None
    
    def get_user_bots(self, user_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Récupère tous les bots d'un utilisateur.
        
        Args:
            user_id: ID de l'utilisateur
            include_inactive: Si True, inclut aussi les bots inactifs de l'arène
            
        Returns:
            Liste de dictionnaires avec infos bots (incluant avatar)
        """
        # Utilise le repository (DIP respecté)
        # Note: only_active=False retourne TOUS les bots (pour Playground)
        bots = self.bot_repo.find_by_user(user_id, only_active=False)
        
        # Utilise to_dict() du modèle pour avoir owner_avatar et owner_username
        return [bot.to_dict(include_code=True) for bot in bots]
    
    def get_all_active_bots(self) -> List[Dict[str, Any]]:
        """Récupère tous les bots actifs dans l'arène (pour sélection adversaire).
        
        Returns:
            Liste de dictionnaires avec infos bots actifs (incluant avatar)
        """
        bots = self.bot_repo.find_all_active()
        # Utilise to_dict() pour avoir owner_avatar et owner_username
        return [bot.to_dict(include_code=False) for bot in bots]
    
    def get_bot_info(self, bot_id: int, user_id: int = None) -> Optional[Dict[str, Any]]:
        """Récupère les informations complètes d'un bot.
        
        Args:
            bot_id: ID du bot
            user_id: ID utilisateur (pour vérification propriété, optionnel)
            
        Returns:
            Dictionnaire avec infos complètes ou None (incluant avatar)
            
        Raises:
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            return None
        
        # Vérification propriété si user_id fourni
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        # Utilise to_dict() pour avoir toutes les infos incluant owner_avatar
        return bot.to_dict(include_code=True)
    
    def get_bot_versions(self, bot_id: int, user_id: int = None) -> List[Dict[str, Any]]:
        """Récupère toutes les versions d'un bot.
        
        Args:
            bot_id: ID du bot
            user_id: ID utilisateur (pour vérification propriété, optionnel)
            
        Returns:
            Liste des versions avec métadonnées
            
        Raises:
            ValueError: Si bot introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        versions = self.bot_repo.get_all_versions(bot_id)
        return [{
            'version_number': v.version_number,
            'version_name': v.version_name if hasattr(v, 'version_name') else f"v{v.version_number}",
            'created_at': v.created_at.isoformat() if v.created_at else None,
            'code_preview': v.code[:100] + '...' if len(v.code) > 100 else v.code
        } for v in versions]
    
    def get_bot_version_code(self, bot_id: int, version_number: int, 
                             user_id: int = None) -> Optional[str]:
        """Récupère le code d'une version spécifique.
        
        Args:
            bot_id: ID du bot
            version_number: Numéro de version
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Code de la version ou None
            
        Raises:
            ValueError: Si bot ou version introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        version = self.bot_repo.get_version(bot_id, version_number)
        if not version:
            raise ValueError(f"Version {version_number} not found for bot {bot_id}")
        
        return version.code
    
    def load_version_to_draft(self, bot_id: int, version_number: int, 
                              user_id: int = None) -> Dict[str, Any]:
        """Charge une version dans le draft (pour édition).
        
        Args:
            bot_id: ID du bot
            version_number: Numéro de version à charger
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Informations du bot avec code chargé
            
        Raises:
            ValueError: Si bot ou version introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        code = self.get_bot_version_code(bot_id, version_number, user_id)
        
        # Met à jour le draft avec ce code
        bot = self.bot_repo.find_by_id(bot_id)
        bot.code = code
        self.bot_repo.save(bot)
        
        self.logger.info(f"Loaded version {version_number} into draft for bot {bot_id}")
        
        return {
            'id': bot.id,
            'name': bot.name,
            'code': bot.code,
            'loaded_version': version_number
        }
    
    def rollback_to_version(self, bot_id: int, version_number: int, 
                           user_id: int = None) -> Dict[str, Any]:
        """Rollback: crée une nouvelle version avec le code d'une ancienne.
        
        Args:
            bot_id: ID du bot
            version_number: Numéro de version source
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Informations de la nouvelle version créée
            
        Raises:
            ValueError: Si bot ou version introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        # Récupère le code de l'ancienne version
        code = self.get_bot_version_code(bot_id, version_number, user_id)
        
        # Crée une nouvelle version avec ce code
        bot = self.bot_repo.find_by_id(bot_id)
        new_version = self.bot_repo.create_version(bot_id, code)
        
        self.logger.info(
            f"Rolled back bot {bot_id} to version {version_number}, "
            f"created new version {new_version.version_number}"
        )
        
        return {
            'bot_id': bot_id,
            'new_version_number': new_version.version_number,
            'rolled_back_from': version_number,
            'created_at': new_version.created_at.isoformat()
        }
    
    def delete_bot(self, bot_id: int, user_id: int = None) -> None:
        """Supprime un bot (soft delete).
        
        Args:
            bot_id: ID du bot
            user_id: ID utilisateur (pour vérification propriété)
            
        Raises:
            ValueError: Si bot introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        self.bot_repo.delete(bot)
        self.logger.info(f"Deleted bot {bot_id}")
    
    def submit_to_arena(self, bot_id: int, version_name: str = None, 
                        description: str = '', user_id: int = None) -> Dict[str, Any]:
        """Soumet un bot à l'arène (crée une nouvelle version stable).
        
        Args:
            bot_id: ID du bot
            version_name: Nom de la version (optionnel)
            description: Description de la version
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Dictionnaire avec infos de la version créée
            
        Raises:
            ValueError: Si bot introuvable ou code invalide
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        # Validation du code actuel (draft)
        if not bot.code or not bot.code.strip():
            raise ValueError("Cannot submit bot with empty code")
        
        is_valid, error = self.validate_bot_code(bot.code)
        if not is_valid:
            raise ValueError(f"Cannot submit bot with invalid code: {error}")
        
        # Création nouvelle version avec metadata
        version = self.bot_repo.create_version(
            bot_id=bot_id,
            code=bot.code,
            version_name=version_name,  # Sera auto-généré si None
            description=description
        )
        
        # Active le bot dans l'arène
        bot.is_active = True
        self.bot_repo.save(bot)
        
        self.logger.info(
            f"Bot {bot_id} submitted to arena as version {version.version_number}"
        )
        
        return {
            'bot_id': bot_id,
            'version_number': version.version_number,
            'version_name': version.version_name,
            'description': version.description,
            'created_at': version.created_at.isoformat()
        }
    
    def deactivate_bot(self, bot_id: int, user_id: int = None) -> Dict[str, Any]:
        """Désactive un bot de l'arène.
        
        Args:
            bot_id: ID du bot
            user_id: ID utilisateur (pour vérification propriété)
            
        Returns:
            Informations du bot désactivé
            
        Raises:
            ValueError: Si bot introuvable
            PermissionError: Si l'utilisateur n'est pas propriétaire
        """
        bot = self.bot_repo.find_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        if user_id and bot.user_id != user_id:
            raise PermissionError(f"User {user_id} does not own bot {bot_id}")
        
        bot.is_active = False
        self.bot_repo.save(bot)
        
        self.logger.info(f"Bot {bot_id} deactivated from arena")
        
        return {
            'id': bot.id,
            'name': bot.name,
            'is_active': bot.is_active,
            'updated_at': bot.updated_at.isoformat() if bot.updated_at else None
        }
