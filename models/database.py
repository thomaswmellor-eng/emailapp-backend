from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
from typing import List, Optional, Dict, Any
from email_validator import validate_email, EmailNotValidError
from pydantic import BaseModel, Field, validator
import json
from config import settings
import re
import urllib.parse
import random
import string
from datetime import timedelta

# Créer le répertoire data s'il n'existe pas
os.makedirs('data', exist_ok=True)

# Utiliser SQLite en production sur Render
if settings.ENVIRONMENT == "production":
    # Use SQLite in production
    engine = create_engine('sqlite:///data/database.db', connect_args={"check_same_thread": False})
else:
    # Use Azure SQL in development
    connection_string = settings.DB_CONNECTION_STRING
    params = dict(param.split('=') for param in connection_string.split(';') if param)
    server = params.get('Server', '').replace('tcp:', '')
    database = params.get('Database', '')
    username = params.get('Uid', '')
    password = params.get('Pwd', '')
    sqlalchemy_url = f"mssql+pyodbc://{username}:{password}@{server}/{database}?driver=ODBC+Driver+18+for+SQL+Server"
    engine = create_engine(sqlalchemy_url, connect_args={"TrustServerCertificate": "yes"})

# Créer une session de base de données
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Créer une base déclarative
Base = declarative_base()

# Association tables pour les relations many-to-many
contact_template = Table(
    "contact_template",
    Base.metadata,
    Column("contact_id", Integer, ForeignKey("contacts.id")),
    Column("template_id", Integer, ForeignKey("templates.id")),
)

friends_association = Table(
    "friends_association",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("friend_id", Integer, ForeignKey("users.id")),
)

# Modèles SQLAlchemy
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    name = Column(String(255))
    position = Column(String(255))
    company = Column(String(255))
    contact = Column(String(255))
    is_active = Column(Boolean, default=True)
    auth_code = Column(String(6), nullable=True)
    auth_code_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    contacts = relationship("Contact", back_populates="user")
    templates = relationship("Template", back_populates="user")
    emails = relationship("EmailStatus", back_populates="user")
    friends = relationship(
        "User", 
        secondary=friends_association,
        primaryjoin=id==friends_association.c.user_id,
        secondaryjoin=id==friends_association.c.friend_id,
    )
    shared_emails = relationship("SharedEmails", back_populates="user", foreign_keys="[SharedEmails.user_id]")

class Contact(Base):
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    first_name = Column(String(255))
    last_name = Column(String(255))
    email = Column(String(255), unique=True, index=True)
    company = Column(String(255))
    position = Column(String(255))
    industry = Column(String(255))
    technologies = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    user = relationship("User", back_populates="contacts")
    emails = relationship("EmailStatus", back_populates="contact")
    templates = relationship("Template", secondary=contact_template, back_populates="contacts")

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String(255))
    subject = Column(String(255))
    body = Column(Text)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    user = relationship("User", back_populates="templates")
    emails = relationship("EmailStatus", back_populates="template")
    contacts = relationship("Contact", secondary=contact_template, back_populates="templates")

class EmailStatus(Base):
    __tablename__ = "email_status"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    subject = Column(String(255))
    body = Column(Text)
    sent_date = Column(DateTime, nullable=True)
    status = Column(String(50))  # draft, sent, opened, replied, bounced
    tracked_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    user = relationship("User", back_populates="emails")
    contact = relationship("Contact", back_populates="emails")
    template = relationship("Template", back_populates="emails")

class SharedEmails(Base):
    __tablename__ = "shared_emails"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    friend_id = Column(Integer, ForeignKey("users.id"))
    contact_email = Column(String(255))
    shared_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    user = relationship("User", back_populates="shared_emails", foreign_keys=[user_id])
    friend = relationship("User", foreign_keys=[friend_id])

class Friend(Base):
    __tablename__ = "friends"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    friend_id = Column(Integer, ForeignKey("users.id"))
    friend_email = Column(String(255))
    status = Column(String(50))  # pending, accepted, rejected
    share_cache = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Créer les tables
def create_tables():
    Base.metadata.create_all(bind=engine)

# Fonction pour obtenir une session de base de données
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Modèles Pydantic pour l'API
class UserBase(BaseModel):
    email: str
    name: Optional[str] = None
    position: Optional[str] = None
    company: Optional[str] = None
    contact: Optional[str] = None
    
    @validator('email')
    def email_must_be_valid(cls, v):
        try:
            validate_email(v)
            return v
        except EmailNotValidError:
            raise ValueError('Email non valide')

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class ContactBase(BaseModel):
    first_name: str
    last_name: str
    email: str
    company: Optional[str] = None
    position: Optional[str] = None
    industry: Optional[str] = None
    technologies: Optional[str] = None
    notes: Optional[str] = None
    
    @validator('email')
    def email_must_be_valid(cls, v):
        try:
            validate_email(v)
            return v
        except EmailNotValidError:
            raise ValueError('Email non valide')

class ContactCreate(ContactBase):
    pass

class ContactResponse(ContactBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class EmailTemplate(BaseModel):
    name: str
    subject: str
    body: str
    is_default: bool = False

class TemplateCreate(EmailTemplate):
    pass

class TemplateResponse(TemplateCreate):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class EmailStatusBase(BaseModel):
    subject: str
    body: str
    status: str = "draft"

class EmailStatusCreate(EmailStatusBase):
    contact_id: int
    template_id: Optional[int] = None

class EmailStatusResponse(EmailStatusBase):
    id: int
    user_id: int
    contact_id: int
    template_id: Optional[int] = None
    sent_date: Optional[datetime] = None
    tracked_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class FriendRequestBase(BaseModel):
    friend_email: str
    
    @validator('friend_email')
    def email_must_be_valid(cls, v):
        try:
            validate_email(v)
            return v
        except EmailNotValidError:
            raise ValueError('Email non valide')

class FriendRequestCreate(FriendRequestBase):
    pass

class FriendRequestResponse(FriendRequestBase):
    id: int
    user_id: int
    status: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class FriendRequestUpdate(BaseModel):
    status: str

class SharedEmailBase(BaseModel):
    friend_id: int
    contact_email: str

class SharedEmailCreate(SharedEmailBase):
    pass

class SharedEmailResponse(SharedEmailBase):
    id: int
    user_id: int
    shared_at: datetime
    
    class Config:
        orm_mode = True

class CacheInfo(BaseModel):
    size: int
    last_updated: Optional[str] = None
    cache_file: str

class EmailContent(BaseModel):
    subject: str
    body: str

class EmailGenerationRequest(BaseModel):
    prospect_info: Dict[str, str]
    template_id: Optional[int] = None
    use_ai: bool = False
    stage: str = "outreach"

class EmailResponse(BaseModel):
    id: int
    to: str
    subject: str
    body: str
    stage: str
    status: str

class BatchEmailResponse(BaseModel):
    emails: List[EmailResponse]

def create_default_template():
    """Crée un template par défaut si aucun n'existe"""
    db = SessionLocal()
    default = db.query(Template).filter(Template.is_default == True).first()
    
    if not default:
        default_template = Template(
            name="Template par défaut",
            subject="Opportunité de collaboration",
            body="""Bonjour {{first_name}},

J'espère que ce message vous trouve bien. Je suis {{your_name}} de {{company_name}}.

Nous aidons des entreprises comme {{company}} à améliorer leurs processus de vente et j'ai pensé que cela pourrait vous intéresser, étant donné votre rôle de {{position}}.

Seriez-vous disponible pour un court appel cette semaine afin que je puisse vous présenter comment nous pourrions vous aider ?

Cordialement,
{{your_name}}
{{your_position}} | {{company_name}}
{{your_contact}}""",
            is_default=True,
            user_id=1  # User ID temporaire
        )
        
        db.add(default_template)
        db.commit()
        db.close()

# Initialize database
def init_db():
    Base.metadata.create_all(bind=engine)
    create_default_template()

# Modèles Pydantic pour l'authentification
class AuthRequest(BaseModel):
    email: str
    
    @validator('email')
    def email_must_be_valid(cls, v):
        try:
            validate_email(v)
            return v
        except EmailNotValidError:
            raise ValueError('Email non valide')

class AuthVerify(BaseModel):
    email: str
    code: str
    
    @validator('email')
    def email_must_be_valid(cls, v):
        try:
            validate_email(v)
            return v
        except EmailNotValidError:
            raise ValueError('Email non valide')
    
    @validator('code')
    def code_must_be_valid(cls, v):
        if not re.match(r'^\d{6}$', v):
            raise ValueError('Code doit être 6 chiffres')
        return v

# Exporter les modèles
__all__ = [
    "get_db", "init_db", "User", "Template", "EmailStatus", "Contact", 
    "Friend", "SharedEmails", "UserBase", "EmailTemplate", "CacheInfo",
    "EmailContent", "FriendRequest", "FriendResponse",
    "EmailGenerationRequest", "EmailResponse", "BatchEmailResponse"
] 