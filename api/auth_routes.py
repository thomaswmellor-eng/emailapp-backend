import os
import random
import string
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import Any, Dict

from models.database import (
    get_db, User, VerificationCode, 
    VerificationCodeCreate, VerificationCodeResponse, VerificationCodeVerify,
    UserCreate, UserResponse
)
from utils.email_sender import EmailSender

# Configuration du logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

router = APIRouter()

def generate_verification_code(length=6):
    """Génère un code de vérification aléatoire"""
    return ''.join(random.choices(string.digits, k=length))

@router.post("/request-code", response_model=VerificationCodeResponse)
async def request_verification_code(
    verification_data: VerificationCodeCreate,
    db: Session = Depends(get_db)
) -> Any:
    """
    Demande un code de vérification pour l'adresse email fournie.
    Le code est envoyé par email et est valide pendant 15 minutes.
    """
    email = verification_data.email
    
    # Générer un code à 6 chiffres
    code = generate_verification_code()
    
    # Date d'expiration (15 minutes)
    expires_at = datetime.utcnow() + timedelta(minutes=15)
    
    # Vérifier si un code existe déjà pour cet email
    existing_code = db.query(VerificationCode).filter(VerificationCode.email == email).first()
    
    if existing_code:
        # Mettre à jour le code existant
        existing_code.code = code
        existing_code.created_at = datetime.utcnow()
        existing_code.expires_at = expires_at
        existing_code.is_used = False
        db.commit()
        db.refresh(existing_code)
        verification_code = existing_code
    else:
        # Créer un nouveau code
        verification_code = VerificationCode(
            email=email,
            code=code,
            expires_at=expires_at
        )
        db.add(verification_code)
        db.commit()
        db.refresh(verification_code)
    
    # Envoyer le code par email
    email_sent = EmailSender.send_verification_code(email, code)
    
    if not email_sent:
        # Si l'email n'a pas pu être envoyé, supprimer le code
        db.delete(verification_code)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="Impossible d'envoyer le code de vérification. Veuillez réessayer plus tard."
        )
    
    return verification_code

@router.post("/verify-code", response_model=UserResponse)
async def verify_code(
    verification_data: VerificationCodeVerify,
    db: Session = Depends(get_db)
) -> Any:
    """
    Vérifie le code envoyé par l'utilisateur.
    Si le code est valide, l'utilisateur est authentifié ou créé si c'est la première connexion.
    """
    email = verification_data.email
    code = verification_data.code
    
    # Rechercher le code de vérification
    verification_code = db.query(VerificationCode).filter(
        VerificationCode.email == email,
        VerificationCode.is_used == False
    ).first()
    
    if not verification_code:
        raise HTTPException(
            status_code=404,
            detail="Aucun code de vérification trouvé pour cet email."
        )
    
    # Vérifier si le code est expiré
    if datetime.utcnow() > verification_code.expires_at:
        raise HTTPException(
            status_code=400,
            detail="Le code de vérification a expiré. Veuillez demander un nouveau code."
        )
    
    # Vérifier si le code est correct
    if verification_code.code != code:
        raise HTTPException(
            status_code=400,
            detail="Code de vérification incorrect."
        )
    
    # Marquer le code comme utilisé
    verification_code.is_used = True
    db.commit()
    
    # Rechercher l'utilisateur existant ou en créer un nouveau
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        # Créer un nouvel utilisateur
        user = User(
            email=email,
            name=email.split('@')[0],  # Nom par défaut basé sur l'email
            company="",
            position="",
            contact_info=email
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Mettre à jour la date de dernière connexion
        user.last_login = datetime.utcnow()
        db.commit()
        db.refresh(user)
    
    # Associer le code de vérification à l'utilisateur
    verification_code.user_id = user.id
    db.commit()
    
    return user

@router.get("/me", response_model=UserResponse)
async def get_current_user(
    email: str,
    db: Session = Depends(get_db)
) -> Any:
    """
    Récupère les informations de l'utilisateur actuellement connecté.
    """
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur non trouvé."
        )
    
    return user

@router.put("/me", response_model=UserResponse)
async def update_user_profile(
    email: str,
    user_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
) -> Any:
    """
    Met à jour le profil de l'utilisateur actuellement connecté.
    """
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur non trouvé."
        )
    
    # Mettre à jour les champs fournis
    if "name" in user_data:
        user.name = user_data["name"]
    if "company" in user_data:
        user.company = user_data["company"]
    if "position" in user_data:
        user.position = user_data["position"]
    if "contact_info" in user_data:
        user.contact_info = user_data["contact_info"]
    
    db.commit()
    db.refresh(user)
    
    return user 