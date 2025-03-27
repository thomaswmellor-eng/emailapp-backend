from pydantic import BaseModel, Field, EmailStr
from typing import List, Dict, Any, Optional
from datetime import datetime

class ContactInfo(BaseModel):
    """Modèle pour les informations de contact"""
    first_name: str
    last_name: str
    email: str
    company: str
    position: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    website: Optional[str] = None
    technologies: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    challenges: Optional[List[str]] = None

class EmailContent(BaseModel):
    """Modèle pour le contenu d'un email"""
    subject: str
    body: str
    to: str = Field(..., description="Adresse email du destinataire")
    contact_info: Optional[Dict[str, Any]] = None

class EmailGenerationResponse(BaseModel):
    """Réponse du serveur pour la génération d'emails"""
    success: bool
    message: str
    is_background: bool = False
    emails: List[Dict[str, Any]] = []

class EmailTemplate(BaseModel):
    """Modèle pour un template d'email"""
    id: str
    name: str
    subject_template: str
    body_template: str
    email_type: str = "outreach"
    last_modified: Optional[datetime] = None
    creator: Optional[str] = None

class CacheInfo(BaseModel):
    """Informations sur le cache d'emails"""
    size: int
    last_updated: Optional[str] = None
    cache_file: str

class CacheEntry(BaseModel):
    """Une entrée dans le cache d'emails"""
    email: EmailStr
    company: str
    timestamp: str
    email_data: Dict[str, str]

class FriendRequest(BaseModel):
    """Demande d'ami"""
    id: str
    email: EmailStr
    name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

class Friend(BaseModel):
    """Ami avec lequel partager le cache"""
    id: str
    email: EmailStr
    name: Optional[str] = None
    sharing_enabled: bool = True
    cache_count: int = 0
    last_sync: Optional[datetime] = None

class FriendResponse(BaseModel):
    """Réponse du serveur pour les opérations liées aux amis"""
    success: bool
    message: str
    friends: List[Friend] = []
    pending_requests: List[FriendRequest] = []
    sent_requests: List[FriendRequest] = []

class SyncCacheRequest(BaseModel):
    """Requête pour synchroniser le cache avec un ami"""
    friend_id: str
    entries: List[CacheEntry] = []

class UserProfile(BaseModel):
    """Modèle pour les profils utilisateurs"""
    id: str
    username: str
    company_name: str
    your_name: str
    your_position: str
    your_contact: str
    created_at: datetime = Field(default_factory=datetime.now)
    last_login: Optional[datetime] = None 