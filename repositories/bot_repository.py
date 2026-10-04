"""Bot Repository - Gestion de la persistence des bots.

Responsabilité (SRP) : Accès aux données des bots uniquement.
- CRUD operations sur Bot et BotVersion
- Queries de recherche
- Pas de logique métier, pas de validation
"""
from typing import Optional, List
from models import db, Bot, BotVersion, User
from datetime import datetime


class BotRepository:
    """Repository pour la gestion de la persistence des bots.
    
    Pattern: Repository Pattern
    SOLID: SRP (une seule responsabilité - accès données)
    """
    
    @staticmethod
    def find_by_id(bot_id: int) -> Optional[Bot]:
        """Trouve un bot par son ID."""
        return Bot.query.get(bot_id)
    
    @staticmethod
    def find_by_user(user_id: int, only_active: bool = False) -> List[Bot]:
        """Trouve tous les bots d'un utilisateur.
        
        Args:
            user_id: ID de l'utilisateur
            only_active: Si True, filtre uniquement les bots actifs dans l'arène
            
        Returns:
            Liste des bots
        """
        if only_active:
            return Bot.query.filter_by(user_id=user_id, is_active=True).all()
        return Bot.query.filter_by(user_id=user_id).all()
    
    @staticmethod
    def find_all_active() -> List[Bot]:
        """Trouve tous les bots actifs dans l'arène (avec au moins une version soumise)."""
        return Bot.query.filter(
            Bot.is_active == True,
            Bot.latest_version_number > 0
        ).all()
    
    @staticmethod
    def save(bot: Bot) -> Bot:
        """Sauvegarde ou met à jour un bot."""
        db.session.add(bot)
        db.session.commit()
        return bot
    
    @staticmethod
    def delete(bot: Bot) -> None:
        """Désactive un bot (le retire de l'arène)."""
        bot.is_active = False
        bot.updated_at = datetime.utcnow()
        db.session.commit()
    
    @staticmethod
    def create(user_id: int, name: str, referee_type: str = 'pacman', 
               code: str = '') -> Bot:
        """Crée un nouveau bot.
        
        Args:
            user_id: ID de l'utilisateur
            name: Nom du bot
            referee_type: Type de referee (pacman, tictactoe, etc.)
            code: Code initial (draft)
        """
        bot = Bot(
            user_id=user_id,
            name=name,
            referee_type=referee_type,
            code=code
        )
        db.session.add(bot)
        db.session.commit()
        return bot
    
    @staticmethod
    def create_version(bot_id: int, code: str, version_number: int = None,
                      version_name: str = None, description: str = '') -> BotVersion:
        """Crée une nouvelle version d'un bot.
        
        Args:
            bot_id: ID du bot
            code: Code de la version
            version_number: Numéro de version (auto-incrémenté si None)
            version_name: Nom de la version (auto-généré si None)
            description: Description de la version
        """
        bot = Bot.query.get(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        if version_number is None:
            # Auto-increment version
            last_version = BotVersion.query.filter_by(bot_id=bot_id)\
                .order_by(BotVersion.version_number.desc()).first()
            version_number = (last_version.version_number + 1) if last_version else 1
        
        # Auto-generate version name if not provided
        if not version_name:
            owner_username = bot.owner.username if bot.owner else 'user'
            version_name = f"{owner_username}_v{version_number}"
        
        version = BotVersion(
            bot_id=bot_id,
            code=code,
            version_number=version_number,
            version_name=version_name,
            description=description
        )
        db.session.add(version)
        
        # Update bot's latest_version_number
        bot.latest_version_number = version_number
        
        db.session.commit()
        return version
    
    @staticmethod
    def get_latest_version(bot_id: int) -> Optional[BotVersion]:
        """Récupère la dernière version d'un bot."""
        return BotVersion.query.filter_by(bot_id=bot_id)\
            .order_by(BotVersion.version_number.desc()).first()
    
    @staticmethod
    def get_version(bot_id: int, version_number: int) -> Optional[BotVersion]:
        """Récupère une version spécifique d'un bot."""
        return BotVersion.query.filter_by(
            bot_id=bot_id, 
            version_number=version_number
        ).first()
    
    @staticmethod
    def get_all_versions(bot_id: int) -> List[BotVersion]:
        """Récupère toutes les versions d'un bot."""
        return BotVersion.query.filter_by(bot_id=bot_id)\
            .order_by(BotVersion.version_number.desc()).all()
