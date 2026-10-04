"""User Repository - Gestion de la persistence des utilisateurs.

Responsabilité (SRP) : Accès aux données des utilisateurs uniquement.
"""
from typing import Optional, List
from models import db, User


class UserRepository:
    """Repository pour la gestion de la persistence des utilisateurs.
    
    Pattern: Repository Pattern
    SOLID: SRP (une seule responsabilité - accès données utilisateurs)
    """
    
    @staticmethod
    def find_by_id(user_id: int) -> Optional[User]:
        """Trouve un utilisateur par son ID."""
        return User.query.get(user_id)
    
    @staticmethod
    def find_by_username(username: str) -> Optional[User]:
        """Trouve un utilisateur par son nom d'utilisateur."""
        return User.query.filter_by(username=username).first()
    
    @staticmethod
    def find_by_email(email: str) -> Optional[User]:
        """Trouve un utilisateur par son email."""
        return User.query.filter_by(email=email).first()
    
    @staticmethod
    def find_all() -> List[User]:
        """Récupère tous les utilisateurs."""
        return User.query.all()
    
    @staticmethod
    def save(user: User) -> User:
        """Sauvegarde ou met à jour un utilisateur."""
        db.session.add(user)
        db.session.commit()
        return user
    
    @staticmethod
    def create(username: str, email: str, password_hash: str) -> User:
        """Crée un nouvel utilisateur."""
        user = User(
            username=username,
            email=email,
            password_hash=password_hash
        )
        db.session.add(user)
        db.session.commit()
        return user
