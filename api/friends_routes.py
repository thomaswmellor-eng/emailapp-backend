from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import logging
import os
from pydantic import BaseModel
from models.database import (
    get_db, User, Friend, SharedEmails, Contact, 
    FriendRequestCreate, FriendRequestResponse, FriendRequestUpdate, 
    SharedEmailCreate, SharedEmailResponse, UserResponse
)
from utils.prospect_email_generator import ProspectEmailGenerator
from datetime import datetime

# Configuration du logging
logger = logging.getLogger("friends_api")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

router = APIRouter(prefix="/friends", tags=["friends"])

# Variables globales
CACHE_FILE = os.environ.get("CACHE_FILE", "email_cache.json")
email_generator = ProspectEmailGenerator(cache_file=CACHE_FILE)

# Fonction utilitaire pour obtenir l'utilisateur courant (dans une application réelle, ce serait basé sur l'authentification)
def get_current_user(db: Session = Depends(get_db)) -> User:
    """
    Obtient l'utilisateur courant ou crée un utilisateur par défaut
    """
    # Simuler un utilisateur authentifié (dans une vraie application, cela viendrait d'un token JWT)
    user = db.query(User).filter(User.email == "user@example.com").first()
    
    if not user:
        # Créer un utilisateur par défaut
        user = User(
            email="user@example.com",
            name=os.environ.get("YOUR_NAME", "John Doe"),
            position=os.environ.get("YOUR_POSITION", "Sales Manager"),
            company=os.environ.get("COMPANY_NAME", "Example Inc"),
            contact_info=os.environ.get("YOUR_CONTACT", "user@example.com")
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    return user

@router.get("/", response_model=Dict[str, Any])
async def get_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupère la liste des amis et des demandes en attente
    """
    # Récupérer les amis acceptés
    accepted_friend_requests = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.status == "accepted"
    ).all()
    
    # Récupérer les demandes d'amis en attente
    pending_friend_requests = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.status == "pending"
    ).all()
    
    # Récupérer les utilisateurs correspondant aux amis acceptés
    friends = []
    for fr in accepted_friend_requests:
        friend_user = db.query(User).filter(User.email == fr.friend_email).first()
        if friend_user:
            # Vérifier si le partage est activé
            sharing_enabled = db.query(SharedEmails).filter(
                SharedEmails.user_id == current_user.id,
                SharedEmails.friend_id == friend_user.id
            ).first() is not None
            
            friends.append({
                "email": friend_user.email,
                "name": friend_user.name,
                "company": friend_user.company,
                "sharing_enabled": sharing_enabled
            })
        else:
            # L'ami n'a pas encore de compte
            friends.append({
                "email": fr.friend_email,
                "name": None,
                "company": None,
                "sharing_enabled": False
            })
    
    # Formater les demandes en attente
    pending_requests = []
    for pr in pending_friend_requests:
        friend_user = db.query(User).filter(User.email == pr.friend_email).first()
        pending_requests.append({
            "email": pr.friend_email,
            "name": friend_user.name if friend_user else None,
            "company": friend_user.company if friend_user else None
        })
    
    return {
        "friends": friends,
        "pending_requests": pending_requests
    }

@router.post("/request", response_model=Dict[str, Any])
async def send_friend_request(
    request: FriendRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Envoie une demande d'ami
    """
    # Vérifier si l'ami existe déjà
    existing_friend = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.friend_email == request.friend_email
    ).first()
    
    if existing_friend:
        if existing_friend.status == "accepted":
            raise HTTPException(status_code=400, detail="Cet utilisateur est déjà votre ami")
        elif existing_friend.status == "pending":
            raise HTTPException(status_code=400, detail="Une demande d'ami est déjà en attente pour cet utilisateur")
        elif existing_friend.status == "rejected":
            # Mettre à jour la demande rejetée en demande en attente
            existing_friend.status = "pending"
            existing_friend.updated_at = datetime.utcnow()
            db.commit()
            return {"message": "Demande d'ami envoyée", "status": "pending"}
    
    # Créer une nouvelle demande d'ami
    new_friend_request = Friend(
        user_id=current_user.id,
        friend_email=request.friend_email,
        status="pending"
    )
    
    db.add(new_friend_request)
    db.commit()
    
    # Créer une demande réciproque si l'autre utilisateur existe
    friend_user = db.query(User).filter(User.email == request.friend_email).first()
    if friend_user:
        reciprocal_request = db.query(Friend).filter(
            Friend.user_id == friend_user.id,
            Friend.friend_email == current_user.email
        ).first()
        
        if not reciprocal_request:
            reciprocal_request = Friend(
                user_id=friend_user.id,
                friend_email=current_user.email,
                status="pending"
            )
            db.add(reciprocal_request)
            db.commit()
    
    return {"message": "Demande d'ami envoyée", "status": "pending"}

@router.put("/request/{email}", response_model=Dict[str, Any])
async def update_friend_request(
    email: str,
    update: FriendRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Accepte ou rejette une demande d'ami
    """
    # Récupérer la demande d'ami
    friend_request = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.friend_email == email
    ).first()
    
    if not friend_request:
        raise HTTPException(status_code=404, detail="Demande d'ami non trouvée")
    
    if friend_request.status != "pending":
        raise HTTPException(status_code=400, detail="Cette demande d'ami a déjà été traitée")
    
    # Mettre à jour le statut de la demande
    friend_request.status = update.status
    friend_request.updated_at = datetime.utcnow()
    db.commit()
    
    if update.status == "accepted":
        # Si la demande est acceptée, mettre à jour la demande réciproque
        friend_user = db.query(User).filter(User.email == email).first()
        if friend_user:
            reciprocal_request = db.query(Friend).filter(
                Friend.user_id == friend_user.id,
                Friend.friend_email == current_user.email
            ).first()
            
            if reciprocal_request:
                reciprocal_request.status = "accepted"
                reciprocal_request.updated_at = datetime.utcnow()
                db.commit()
        
        return {"message": "Demande d'ami acceptée", "status": "accepted"}
    else:
        return {"message": "Demande d'ami rejetée", "status": "rejected"}

@router.delete("/{email}", response_model=Dict[str, Any])
async def remove_friend(
    email: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprime un ami
    """
    # Récupérer l'ami
    friend_request = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.friend_email == email
    ).first()
    
    if not friend_request:
        raise HTTPException(status_code=404, detail="Ami non trouvé")
    
    # Supprimer l'ami
    db.delete(friend_request)
    db.commit()
    
    # Supprimer également la relation réciproque
    friend_user = db.query(User).filter(User.email == email).first()
    if friend_user:
        reciprocal_request = db.query(Friend).filter(
            Friend.user_id == friend_user.id,
            Friend.friend_email == current_user.email
        ).first()
        
        if reciprocal_request:
            db.delete(reciprocal_request)
            db.commit()
        
        # Supprimer également les partages
        shared_emails = db.query(SharedEmails).filter(
            (SharedEmails.user_id == current_user.id) & (SharedEmails.friend_id == friend_user.id) |
            (SharedEmails.user_id == friend_user.id) & (SharedEmails.friend_id == current_user.id)
        ).all()
        
        for shared_email in shared_emails:
            db.delete(shared_email)
        
        db.commit()
    
    return {"message": "Ami supprimé avec succès"}

@router.put("/{email}/sharing", response_model=Dict[str, Any])
async def update_friend_sharing(
    email: str,
    update: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Active ou désactive le partage de cache avec un ami
    """
    # Vérifier que l'ami existe
    friend_request = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.friend_email == email,
        Friend.status == "accepted"
    ).first()
    
    if not friend_request:
        raise HTTPException(status_code=404, detail="Ami non trouvé ou relation non confirmée")
    
    # Récupérer l'utilisateur ami
    friend_user = db.query(User).filter(User.email == email).first()
    if not friend_user:
        raise HTTPException(status_code=404, detail="Utilisateur ami non trouvé")
    
    # Vérifier si le partage est déjà activé
    existing_sharing = db.query(SharedEmails).filter(
        SharedEmails.user_id == current_user.id,
        SharedEmails.friend_id == friend_user.id
    ).first()
    
    sharing_enabled = update.get("sharing_enabled", False)
    
    if sharing_enabled and not existing_sharing:
        # Activer le partage
        # Pour chaque contact dans le cache de l'utilisateur, ajouter un enregistrement de partage
        cache = email_generator.cache
        
        for cache_key, cache_data in cache.items():
            contact_info = cache_data.get("contact_info", {})
            contact_email = contact_info.get("email", "")
            
            if contact_email:
                # Vérifier si le contact existe déjà dans la base de données
                contact = db.query(Contact).filter(
                    Contact.email == contact_email,
                    Contact.user_id == current_user.id
                ).first()
                
                if not contact:
                    # Créer le contact dans la base de données
                    contact = Contact(
                        user_id=current_user.id,
                        email=contact_email,
                        first_name=contact_info.get("first_name", ""),
                        last_name=contact_info.get("last_name", ""),
                        company=contact_info.get("company", ""),
                        position=contact_info.get("position", ""),
                        industry=contact_info.get("industry", ""),
                        technologies=contact_info.get("technologies", "")
                    )
                    db.add(contact)
                    db.commit()
                
                # Créer l'enregistrement de partage
                shared_email = SharedEmails(
                    user_id=current_user.id,
                    friend_id=friend_user.id,
                    contact_email=contact_email
                )
                db.add(shared_email)
        
        db.commit()
        return {"message": "Partage activé avec succès", "sharing_enabled": True}
    
    elif not sharing_enabled and existing_sharing:
        # Désactiver le partage
        shared_emails = db.query(SharedEmails).filter(
            SharedEmails.user_id == current_user.id,
            SharedEmails.friend_id == friend_user.id
        ).all()
        
        for shared_email in shared_emails:
            db.delete(shared_email)
        
        db.commit()
        return {"message": "Partage désactivé avec succès", "sharing_enabled": False}
    
    # Pas de changement
    return {"message": "Aucun changement effectué", "sharing_enabled": sharing_enabled}

@router.get("/shared-emails", response_model=List[str])
async def get_shared_emails(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupère la liste des emails partagés avec l'utilisateur
    """
    # Récupérer tous les partages pour l'utilisateur courant
    shared_emails = db.query(SharedEmails).filter(
        SharedEmails.friend_id == current_user.id
    ).all()
    
    # Extraire les emails
    emails = [se.contact_email for se in shared_emails]
    
    return emails

@router.post("/check-shared", response_model=Dict[str, Any])
async def check_shared_emails(
    contacts: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Vérifie si des emails sont déjà partagés avec l'utilisateur
    """
    # Récupérer tous les partages pour l'utilisateur courant
    shared_emails = db.query(SharedEmails).filter(
        SharedEmails.friend_id == current_user.id
    ).all()
    
    # Extraire les emails partagés
    shared_email_addresses = {se.contact_email for se in shared_emails}
    
    # Vérifier chaque contact
    shared_contacts = []
    for contact in contacts:
        email = contact.get("email", "")
        if email and email in shared_email_addresses:
            shared_contacts.append(email)
    
    return {
        "total": len(contacts),
        "shared": len(shared_contacts),
        "shared_emails": shared_contacts
    } 