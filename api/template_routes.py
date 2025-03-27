from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from models.database import get_db, Template
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

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
async def get_all_templates(db: Session = Depends(get_db)):
    """Récupérer tous les templates disponibles"""
    templates = db.query(Template).all()
    return templates

@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: int, db: Session = Depends(get_db)):
    """Récupérer un template spécifique par son ID"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template

@router.post("/", response_model=TemplateResponse)
async def create_template(template: TemplateCreate, db: Session = Depends(get_db)):
    """Créer un nouveau template"""
    # Gérer le cas où ce template serait défini comme défaut
    if template.is_default:
        # Désactiver les autres templates par défaut
        db.query(Template).filter(Template.is_default == True).update({"is_default": False})
        
    new_template = Template(**template.dict())
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template

@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(template_id: int, template_data: TemplateUpdate, db: Session = Depends(get_db)):
    """Mettre à jour un template existant"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Mettre à jour les champs modifiés
    update_data = template_data.dict(exclude_unset=True)
    
    # Gérer le cas où ce template serait défini comme défaut
    if "is_default" in update_data and update_data["is_default"]:
        # Désactiver les autres templates par défaut
        db.query(Template).filter(Template.is_default == True).update({"is_default": False})
    
    for key, value in update_data.items():
        setattr(template, key, value)
    
    template.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(template)
    return template

@router.delete("/{template_id}")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    """Supprimer un template"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    db.delete(template)
    db.commit()
    return {"message": "Template deleted successfully"} 