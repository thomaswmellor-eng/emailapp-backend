import os
import random
import string
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from models.database import User, AuthRequest, AuthVerify, UserResponse, get_db

router = APIRouter()

def generate_auth_code():
    """Génère un code d'authentification à 6 chiffres"""
    return ''.join(random.choices(string.digits, k=6))

def send_auth_email(recipient_email: str, auth_code: str):
    """Envoie un email avec le code d'authentification"""
    sender_email = "no-reply@wesiagency.com"
    message = MIMEMultipart("alternative")
    message["Subject"] = "Votre code d'authentification"
    message["From"] = sender_email
    message["To"] = recipient_email

    # Texte de l'email
    text = f"""
    Bonjour,
    
    Votre code d'authentification pour l'application Email Generator est : {auth_code}
    
    Ce code est valable pendant 15 minutes.
    
    Cordialement,
    L'équipe WesiAgency
    """

    # HTML de l'email
    html = f"""
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

    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")
    message.attach(part1)
    message.attach(part2)

    try:
        # Utilisation du relais SMTP Localhost sans authentification
        with smtplib.SMTP("localhost", 25) as server:
            server.sendmail(sender_email, recipient_email, message.as_string())
        return True
    except Exception as e:
        print(f"Erreur d'envoi d'email: {e}")
        # Fallback : simuler l'envoi pour le développement
        print(f"[DEV] Code d'authentification pour {recipient_email}: {auth_code}")
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
        return {"message": "Code d'authentification envoyé par email"}
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de l'enregistrement du code d'authentification"
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