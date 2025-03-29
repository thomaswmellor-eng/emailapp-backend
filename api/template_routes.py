from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from models.database import get_db, Template, TemplateCreate, TemplateResponse, User
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from utils.auth import get_current_user

router = APIRouter()

# Modèles Pydantic pour la validation des données
class TemplateBase(BaseModel):
    name: str
    subject: str
    body: str
    is_default: bool = False

class TemplateCreate(TemplateBase):
    pass

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    is_default: Optional[bool] = None

class TemplateResponse(TemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# Routes pour les templates
@router.get("/", response_model=List[TemplateResponse])
def get_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Récupérer tous les templates de l'utilisateur"""
    templates = db.query(Template).filter(Template.user_id == current_user.id).all()
    return templates

@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Récupérer un template par son ID"""
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.user_id == current_user.id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    return template

@router.post("/", response_model=TemplateResponse)
def create_template(template: TemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Créer un nouveau template"""
    # Si le template est marqué comme par défaut, désactiver tous les autres templates par défaut
    if template.is_default:
        db.query(Template).filter(
            Template.user_id == current_user.id, 
            Template.is_default == True
        ).update({"is_default": False})
    
    # Créer le nouveau template
    db_template = Template(
        user_id=current_user.id,
        name=template.name,
        subject=template.subject,
        body=template.body,
        is_default=template.is_default
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template

@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, template_data: TemplateCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Mettre à jour un template"""
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.user_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    
    # Si le nouveau template est marqué comme par défaut, désactiver tous les autres templates par défaut
    if template_data.is_default and not template.is_default:
        db.query(Template).filter(
            Template.user_id == current_user.id, 
            Template.is_default == True
        ).update({"is_default": False})
    
    # Mettre à jour le template
    template.name = template_data.name
    template.subject = template_data.subject
    template.body = template_data.body
    template.is_default = template_data.is_default
    
    db.commit()
    db.refresh(template)
    return template

@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Supprimer un template"""
    template = db.query(Template).filter(
        Template.id == template_id,
        Template.user_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    
    db.delete(template)
    db.commit()
    return {"message": "Template supprimé avec succès"} 