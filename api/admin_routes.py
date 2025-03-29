from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from models.database import get_db, User, EmailStatus, Contact, Template, SharedEmails
from config import settings
import os
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Clé d'administration pour sécuriser les endpoints
ADMIN_KEY = os.getenv("ADMIN_KEY", "admin_secret_key")

def verify_admin_key(admin_key: str):
    """Vérifie que la clé d'administration est correcte"""
    if admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé d'administration invalide"
        )
    return True

@router.post("/reset-emails")
async def reset_emails(admin_key: str, db: Session = Depends(get_db)):
    """Supprime tous les emails de la base de données"""
    verify_admin_key(admin_key)
    
    try:
        # Supprimer tous les emails
        deleted_count = db.query(EmailStatus).delete()
        db.commit()
        logger.info(f"Base de données réinitialisée: {deleted_count} emails supprimés")
        return {"message": f"{deleted_count} emails ont été supprimés avec succès"}
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la réinitialisation de la base de données: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la réinitialisation de la base de données: {str(e)}"
        )

@router.post("/reset-users")
async def reset_users(admin_key: str, db: Session = Depends(get_db)):
    """Supprime tous les utilisateurs sauf ceux spécifiés"""
    verify_admin_key(admin_key)
    
    # Liste d'emails d'utilisateurs à conserver
    preserve_emails = ["tom@wesiagency.com", "admin@example.com"]
    
    try:
        # Supprimer les utilisateurs qui ne sont pas dans la liste à préserver
        deleted_count = db.query(User).filter(~User.email.in_(preserve_emails)).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Utilisateurs réinitialisés: {deleted_count} utilisateurs supprimés, {len(preserve_emails)} préservés")
        return {"message": f"{deleted_count} utilisateurs ont été supprimés avec succès"}
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la réinitialisation des utilisateurs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la réinitialisation des utilisateurs: {str(e)}"
        )

@router.get("/database-info")
async def get_database_info(admin_key: str, db: Session = Depends(get_db)):
    """Retourne des informations sur la base de données"""
    verify_admin_key(admin_key)
    
    try:
        users_count = db.query(User).count()
        emails_count = db.query(EmailStatus).count()
        contacts_count = db.query(Contact).count()
        templates_count = db.query(Template).count()
        shared_emails_count = db.query(SharedEmails).count()
        
        return {
            "users_count": users_count,
            "emails_count": emails_count,
            "contacts_count": contacts_count,
            "templates_count": templates_count,
            "shared_emails_count": shared_emails_count
        }
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des informations de la base de données: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des informations de la base de données: {str(e)}"
        ) 