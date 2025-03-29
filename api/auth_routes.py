import os
import random
import string
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional
from datetime import datetime, timedelta
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from models.database import User, AuthRequest, AuthVerify, UserResponse, get_db
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

def generate_auth_code():
    """Génère un code d'authentification à 6 chiffres"""
    return ''.join(random.choices(string.digits, k=6))

def send_auth_email(recipient_email: str, auth_code: str):
    """Envoie un email avec le code d'authentification via SendGrid"""
    sender_email = os.getenv("SENDGRID_FROM_EMAIL", "no-reply@wesiagency.com")
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
    
    # Texte de l'email
    text_content = f"""
    Bonjour,
    
    Votre code d'authentification pour l'application Email Generator est : {auth_code}
    
    Ce code est valable pendant 15 minutes.
    
    Cordialement,
    L'équipe WesiAgency
    """

    # HTML de l'email
    html_content = f"""
    <html>
      <body>
        <p>Bonjour,</p>
        <p>Votre code d'authentification pour l'application <b>Email Generator</b> est :</p>
        <h2 style="color: #4a86e8; font-size: 24px; padding: 10px; background-color: #f2f2f2; border-radius: 5px; text-align: center;">{auth_code}</h2>
        <p>Ce code est valable pendant 15 minutes.</p>
        <p>Cordialement,<br>L'équipe WesiAgency</p>
      </body>
    </html>
    """

    message = Mail(
        from_email=sender_email,
        to_emails=recipient_email,
        subject="Votre code d'authentification",
        plain_text_content=text_content,
        html_content=html_content
    )
    
    try:
        if sendgrid_api_key:
            sg = SendGridAPIClient(sendgrid_api_key)
            response = sg.send(message)
            logger.info(f"Email envoyé à {recipient_email}, statut: {response.status_code}")
            return True
        else:
            # Pas de clé API SendGrid, log pour le développement
            logger.warning(f"[DEV] SendGrid API Key manquante. Code d'authentification pour {recipient_email}: {auth_code}")
            return False
    except Exception as e:
        logger.error(f"Erreur d'envoi d'email: {e}")
        # Fallback : simuler l'envoi pour le développement
        logger.info(f"[DEV] Code d'authentification pour {recipient_email}: {auth_code}")
        return False

@router.post("/request", status_code=status.HTTP_202_ACCEPTED)
def request_auth_code(request: AuthRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Demande un code d'authentification par email"""
    
    # Générer un code d'authentification
    auth_code = generate_auth_code()
    auth_expires = datetime.utcnow() + timedelta(minutes=15)
    
    # Chercher l'utilisateur par email
    user = db.query(User).filter(User.email == request.email).first()
    
    if user:
        # Mettre à jour le code d'authentification
        user.auth_code = auth_code
        user.auth_code_expires_at = auth_expires
    else:
        # Créer un nouvel utilisateur
        user = User(
            email=request.email,
            auth_code=auth_code,
            auth_code_expires_at=auth_expires
        )
        db.add(user)
    
    try:
        db.commit()
        # Envoyer l'email en arrière-plan
        background_tasks.add_task(send_auth_email, request.email, auth_code)
        
        # En mode développement, renvoyer le code dans la réponse
        if settings.ENVIRONMENT == "development" or not os.getenv("SENDGRID_API_KEY"):
            return {"message": "Code d'authentification envoyé par email", "debug_code": auth_code}
        
        return {"message": "Code d'authentification envoyé par email"}
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Erreur de base de données: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de l'enregistrement du code d'authentification"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur inattendue: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Une erreur est survenue: {str(e)}"
        )

@router.post("/verify", response_model=UserResponse)
def verify_auth_code(request: AuthVerify, db: Session = Depends(get_db)):
    """Vérifie le code d'authentification"""
    
    user = db.query(User).filter(User.email == request.email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    if user.auth_code != request.code:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Code d'authentification invalide"
        )
    
    if user.auth_code_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Code d'authentification expiré"
        )
    
    # Réinitialiser le code d'authentification après vérification
    user.auth_code = None
    user.auth_code_expires_at = None
    db.commit()
    
    return user 