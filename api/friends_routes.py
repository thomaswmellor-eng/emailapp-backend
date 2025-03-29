from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional
import logging
import os
from pydantic import BaseModel
from models.database import (
    get_db, User, Friend, SharedEmails, Contact, 
    FriendRequestCreate, FriendRequestResponse, FriendRequestUpdate, 
    SharedEmailCreate, SharedEmailResponse, UserResponse,
    FriendRequestBase, SharedEmailBase
)
from utils.prospect_email_generator import ProspectEmailGenerator
from utils.auth import get_current_user
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

@router.get("/list", response_model=List[Dict[str, Any]])
def get_friends_list(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Récupérer la liste des amis"""
    friends = db.query(Friend).filter(
        Friend.user_id == current_user.id, 
        Friend.status == "accepted"
    ).all()
    
    friends_list = []
    for friend in friends:
        friend_user = db.query(User).filter(User.id == friend.friend_id).first()
        if friend_user:
            friends_list.append({
                "id": friend.id,
                "friend_id": friend.friend_id,
                "friend_email": friend.friend_email,
                "friend_name": friend_user.name,
                "share_cache": friend.share_cache,
                "created_at": friend.created_at
            })
    
    return friends_list

@router.get("/requests", response_model=List[Dict[str, Any]])
def get_friend_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Récupérer les demandes d'amis reçues"""
    # Trouver les demandes d'amis où l'email de l'utilisateur courant est le destinataire
    received_requests = db.query(Friend).join(
        User, User.id == Friend.user_id
    ).filter(
        Friend.friend_email == current_user.email,
        Friend.status == "pending"
    ).all()
    
    requests_list = []
    for request in received_requests:
        sender = db.query(User).filter(User.id == request.user_id).first()
        if sender:
            requests_list.append({
                "id": request.id,
                "sender_id": sender.id,
                "sender_email": sender.email,
                "sender_name": sender.name,
                "created_at": request.created_at
            })
    
    return requests_list

@router.post("/request", status_code=201)
def send_friend_request(
    request: FriendRequestCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Envoyer une demande d'ami"""
    # Vérifier si l'utilisateur s'envoie une demande à lui-même
    if request.friend_email == current_user.email:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous envoyer une demande d'ami à vous-même")
    
    # Vérifier si le destinataire existe déjà
    friend_user = db.query(User).filter(User.email == request.friend_email).first()
    friend_id = friend_user.id if friend_user else None
    
    # Vérifier si une demande existe déjà
    existing_request = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.friend_email == request.friend_email
    ).first()
    
    if existing_request:
        if existing_request.status == "accepted":
            raise HTTPException(status_code=400, detail="Cette personne est déjà votre ami")
        elif existing_request.status == "pending":
            raise HTTPException(status_code=400, detail="Une demande d'ami est déjà en attente pour cet utilisateur")
        elif existing_request.status == "rejected":
            # Mettre à jour la demande rejetée
            existing_request.status = "pending"
            db.commit()
            return {"message": "Demande d'ami envoyée à nouveau"}
    
    # Créer une nouvelle demande d'ami
    new_request = Friend(
        user_id=current_user.id,
        friend_id=friend_id,
        friend_email=request.friend_email,
        status="pending",
        share_cache=False
    )
    
    try:
        db.add(new_request)
        db.commit()
        return {"message": "Demande d'ami envoyée avec succès"}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Erreur lors de l'envoi de la demande d'ami: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'envoi de la demande d'ami")

@router.post("/respond")
def respond_to_friend_request(
    response: FriendRequestUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Répondre à une demande d'ami"""
    # Trouver la demande d'ami correspondante
    friend_request = db.query(Friend).filter(
        Friend.id == response.request_id
    ).first()
    
    if not friend_request:
        raise HTTPException(status_code=404, detail="Demande d'ami non trouvée")
    
    # Vérifier que la demande concerne bien l'utilisateur courant
    if friend_request.friend_email != current_user.email:
        raise HTTPException(status_code=403, detail="Vous n'êtes pas autorisé à répondre à cette demande")
    
    # Mettre à jour le statut de la demande
    if response.status not in ["accepted", "rejected"]:
        raise HTTPException(status_code=400, detail="Statut invalide. Valeurs acceptées: 'accepted', 'rejected'")
    
    friend_request.status = response.status
    
    # Si la demande est acceptée, créer une relation ami dans l'autre sens aussi
    if response.status == "accepted":
        # Vérifier si la relation inverse existe déjà
        existing_inverse = db.query(Friend).filter(
            Friend.user_id == current_user.id,
            Friend.friend_id == friend_request.user_id
        ).first()
        
        if not existing_inverse:
            # Créer la relation inverse
            sender = db.query(User).filter(User.id == friend_request.user_id).first()
            if sender:
                new_friend = Friend(
                    user_id=current_user.id,
                    friend_id=sender.id,
                    friend_email=sender.email,
                    status="accepted",
                    share_cache=False
                )
                db.add(new_friend)
    
    try:
        db.commit()
        return {"message": f"Demande d'ami {response.status}"}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Erreur lors de la réponse à la demande d'ami: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de la réponse à la demande d'ami")

@router.post("/share/{friend_id}")
def toggle_share_with_friend(
    friend_id: int, 
    share: bool = Body(..., embed=True), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Activer/désactiver le partage de cache avec un ami"""
    # Vérifier si l'ami existe
    friend = db.query(Friend).filter(
        Friend.id == friend_id,
        Friend.user_id == current_user.id,
        Friend.status == "accepted"
    ).first()
    
    if not friend:
        raise HTTPException(status_code=404, detail="Ami non trouvé")
    
    # Mettre à jour le statut de partage
    friend.share_cache = share
    
    try:
        db.commit()
        return {"message": f"Partage de cache {'activé' if share else 'désactivé'} avec succès"}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Erreur lors de la mise à jour du partage: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de la mise à jour du partage")

@router.get("/shared-emails", response_model=List[Dict[str, Any]])
def get_shared_emails(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Récupérer les emails partagés par les amis"""
    # Trouver les amis qui partagent leur cache avec l'utilisateur courant
    sharing_friends = db.query(Friend).filter(
        Friend.user_id != current_user.id,  # Ne pas inclure l'utilisateur lui-même
        Friend.friend_id == current_user.id,  # Amis de l'utilisateur courant
        Friend.status == "accepted",  # Relation acceptée
        Friend.share_cache == True  # Partage activé
    ).all()
    
    shared_emails = []
    
    # Pour chaque ami qui partage, récupérer les emails partagés
    for friend in sharing_friends:
        # Récupérer l'utilisateur ami
        friend_user = db.query(User).filter(User.id == friend.user_id).first()
        if not friend_user:
            continue
        
        # Récupérer les emails partagés par cet ami
        emails = db.query(SharedEmails).filter(
            SharedEmails.user_id == friend.user_id,
            SharedEmails.friend_id == current_user.id
        ).all()
        
        for email in emails:
            shared_emails.append({
                "id": email.id,
                "friend_id": friend.user_id,
                "friend_email": friend_user.email,
                "friend_name": friend_user.name,
                "contact_email": email.contact_email,
                "shared_at": email.shared_at
            })
    
    return shared_emails

@router.post("/share-email")
def share_email_with_friends(
    email_data: Dict[str, Any] = Body(...), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Partager un email avec les amis"""
    if "email" not in email_data:
        raise HTTPException(status_code=400, detail="L'email à partager est requis")
    
    contact_email = email_data["email"]
    
    # Trouver les amis avec qui l'utilisateur partage son cache
    sharing_friends = db.query(Friend).filter(
        Friend.user_id == current_user.id,
        Friend.status == "accepted",
        Friend.share_cache == True
    ).all()
    
    if not sharing_friends:
        return {"message": "Aucun ami avec qui partager l'email"}
    
    # Partager l'email avec tous les amis
    for friend in sharing_friends:
        # Vérifier si l'email est déjà partagé avec cet ami
        existing_share = db.query(SharedEmails).filter(
            SharedEmails.user_id == current_user.id,
            SharedEmails.friend_id == friend.friend_id,
            SharedEmails.contact_email == contact_email
        ).first()
        
        if not existing_share:
            new_share = SharedEmails(
                user_id=current_user.id,
                friend_id=friend.friend_id,
                contact_email=contact_email
            )
            db.add(new_share)
    
    try:
        db.commit()
        return {"message": f"Email partagé avec {len(sharing_friends)} ami(s)"}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Erreur lors du partage de l'email: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors du partage de l'email")

@router.delete("/{friend_id}")
def remove_friend(
    friend_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Supprimer un ami"""
    # Trouver l'ami à supprimer
    friend = db.query(Friend).filter(
        Friend.id == friend_id,
        Friend.user_id == current_user.id
    ).first()
    
    if not friend:
        raise HTTPException(status_code=404, detail="Ami non trouvé")
    
    # Supprimer aussi la relation inverse
    inverse_friend = db.query(Friend).filter(
        Friend.user_id == friend.friend_id,
        Friend.friend_id == current_user.id
    ).first()
    
    try:
        db.delete(friend)
        if inverse_friend:
            db.delete(inverse_friend)
        db.commit()
        return {"message": "Ami supprimé avec succès"}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Erreur lors de la suppression de l'ami: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de la suppression de l'ami") 