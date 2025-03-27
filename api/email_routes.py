import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Dict, Any, Optional
import tempfile
import shutil
import csv
import json
from sqlalchemy.orm import Session
import pandas as pd
import logging
from datetime import datetime
from models.database import (
    get_db, EmailStatus, Template, Contact, SharedEmails, Friend, 
    EmailTemplate, CacheInfo, EmailContent, EmailGenerationRequest, BatchEmailResponse
)
from utils.prospect_email_generator import ProspectEmailGenerator, generate_email_content_with_ai
import io

# Setup logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

router = APIRouter()

# Initialiser le générateur d'emails avec un cache par défaut
email_generator = ProspectEmailGenerator()

# Ajouter cette fonction pour convertir le format Apollo
def map_apollo_columns(df):
    """
    Convertit les colonnes du format Apollo CSV vers le format attendu par l'application
    """
    # Mapping de tous les noms de colonnes possibles (en minuscules)
    column_mapping = {
        # Apollo CSV standard
        'first name': 'first_name',
        'last name': 'last_name',
        'title': 'position',
        'company': 'company',
        'company name': 'company',
        'company name for emails': 'company',
        'email': 'email',
        'industry': 'industry',
        'technologies': 'technologies',
        
        # Autres formats possibles
        'prénom': 'first_name',
        'nom': 'last_name',
        'poste': 'position',
        'titre': 'position',
        'entreprise': 'company',
        'société': 'company',
        'e-mail': 'email',
        'mail': 'email',
        'courriel': 'email',
        'secteur': 'industry',
        'technologie': 'technologies',
        'technologie(s)': 'technologies'
    }
    
    logger.info("Original column names: " + ", ".join(df.columns.tolist()))
    
    # Renommer les colonnes si elles existent
    for apollo_col, app_col in column_mapping.items():
        if apollo_col in df.columns:
            df = df.rename(columns={apollo_col: app_col})
            logger.info(f"Renamed column: {apollo_col} -> {app_col}")
    
    logger.info("After renaming: " + ", ".join(df.columns.tolist()))
    
    # S'assurer que toutes les colonnes requises existent (même si elles sont vides)
    for col in ['first_name', 'last_name', 'position', 'company', 'email', 'industry', 'technologies']:
        if col not in df.columns:
            df[col] = ""
            logger.info(f"Added missing column: {col}")
            
    # Si 'technologies' est une chaîne séparée par des virgules, la conserver telle quelle
    # Si 'industry' n'existe pas mais 'keywords' existe, utiliser les premiers mots-clés
    if 'keywords' in df.columns and ('industry' not in df.columns or df['industry'].eq('').all()):
        df['industry'] = df['keywords'].apply(lambda x: x.split(',')[0] if isinstance(x, str) else "")
        logger.info("Used Keywords for industry")
    
    # Vérification finale critique pour l'email
    if 'email' not in df.columns or df['email'].isnull().all() or df['email'].eq('').all():
        # Tenter de récupérer l'email depuis d'autres colonnes qui pourraient contenir des emails
        email_variants = ['mail', 'e-mail', 'courriel']
        email_like_cols = [c for c in df.columns if any(variant in c.lower() for variant in email_variants)]
        
        for email_col in email_like_cols:
            if email_col != 'email' and not df[email_col].eq('').all():
                df['email'] = df[email_col]
                logger.info(f"Recovered email from {email_col} column")
                break
    
    return df

@router.post("/generate", response_model=Dict[str, Any])
async def generate_emails(
    file: UploadFile = File(...),
    stage: str = Form("outreach"),
    your_name: Optional[str] = Form(None),
    your_position: Optional[str] = Form(None),
    company_name: Optional[str] = Form(None),
    your_contact: Optional[str] = Form(None),
    use_ai: bool = Form(False),
    template_id: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Génère des emails pour une liste de contacts à partir d'un fichier CSV
    """
    logger.info(f"Generate emails called: stage={stage}, use_ai={use_ai}, template_id={template_id}")
    logger.info(f"File received: {file.filename}")
    
    # Validate stage
    valid_stages = ['outreach', 'followup', 'lastchance']
    if stage not in valid_stages:
        stage = 'outreach'
    
    # Vérifier le format du fichier
    if file.filename.endswith('.csv'):
        try:
            # Lire le fichier CSV
            contents = await file.read()
            logger.info(f"CSV file read, content length: {len(contents)}")
            
            # Afficher les premiers octets pour débogage
            preview = contents[:100].decode('utf-8', errors='replace')
            logger.info(f"CSV preview: {preview}")
            
            # Essayer plusieurs encodages si nécessaire
            encodings = ['utf-8', 'latin-1', 'cp1252']
            df = None
            
            for encoding in encodings:
                try:
                    logger.info(f"Trying to parse CSV with encoding: {encoding}")
                    df = pd.read_csv(io.StringIO(contents.decode(encoding)))
                    logger.info(f"Successfully parsed with encoding: {encoding}")
                    break
                except UnicodeDecodeError:
                    logger.warning(f"Failed to decode with {encoding}")
                except Exception as e:
                    logger.warning(f"Error parsing CSV with {encoding}: {str(e)}")
            
            if df is None:
                raise HTTPException(
                    status_code=400,
                    detail="Could not parse CSV file with any supported encoding"
                )
            
            # Cas spécial: aucune colonne détectée
            if len(df.columns) <= 1:
                logger.warning("Only one column detected. This might be due to incorrect delimiter.")
                # Essayer avec d'autres délimiteurs
                for delimiter in [',', ';', '\t', '|']:
                    try:
                        df = pd.read_csv(io.StringIO(contents.decode('utf-8')), delimiter=delimiter)
                        if len(df.columns) > 1:
                            logger.info(f"Successfully parsed CSV with delimiter: {delimiter}")
                            break
                    except Exception as e:
                        logger.warning(f"Error parsing CSV with delimiter {delimiter}: {str(e)}")
            
            original_columns = list(df.columns)
            logger.info(f"Original columns: {original_columns}")
            
            # Vérifier si 'Email' (avec majuscule) existe avant de normaliser
            has_email_column = any(col in ['Email', 'email', 'E-mail', 'e-mail'] for col in original_columns)
            logger.info(f"Has email column: {has_email_column}")
            
            # Normaliser les noms de colonnes (convertir tout en minuscules pour simplifier)
            df.columns = [col.lower() for col in df.columns]
            logger.info(f"Normalized column names: {', '.join(df.columns.tolist())}")
            
            # Si la colonne email n'existait pas mais existe maintenant, c'est qu'elle a été normalisée
            if not has_email_column and 'email' in df.columns:
                logger.info("Email column found after normalization")
                has_email_column = True
            
            # Traiter le format Apollo
            if 'first name' in df.columns or 'last name' in df.columns:
                logger.info("Apollo CSV format detected, mapping columns...")
                df = map_apollo_columns(df)
                logger.info(f"After mapping: {', '.join(df.columns.tolist())}")
            
            # SOLUTION IMMÉDIATE : Créer la colonne email si elle n'existe pas
            if 'email' not in df.columns:
                logger.warning("Email column not found, looking for alternatives")
                # Chercher d'autres colonnes qui pourraient contenir les emails
                # Essayer différentes variantes de "email"
                email_variants = ['mail', 'e-mail', 'courriel', 'Email', 'E-mail']
                email_like_cols = [c for c in df.columns if any(variant in c.lower() for variant in email_variants)]
                
                if email_like_cols:
                    # Utiliser la première colonne qui contient "email" dans son nom
                    email_col = email_like_cols[0]
                    logger.info(f"Using column '{email_col}' as email")
                    df['email'] = df[email_col]
                else:
                    # SOLUTION DE CONTOURNEMENT : Si aucune colonne d'email n'est trouvée, utiliser la 3ème colonne
                    # (Dans Apollo CSV, la colonne Email est généralement la 3ème)
                    if len(df.columns) >= 3:
                        logger.warning(f"No email column found, using column '{df.columns[2]}' as backup")
                        df['email'] = df[df.columns[2]]
                    else:
                        logger.error("No suitable email column found and not enough columns to guess")
                        raise HTTPException(
                            status_code=400,
                            detail=f"CSV file must contain 'email' column. Found columns: {', '.join(df.columns.tolist())}"
                        )
            
            # Vérifier que les emails sont non-vides
            if df['email'].isnull().all() or df['email'].eq('').all():
                logger.error("Email column exists but all values are empty")
                raise HTTPException(
                    status_code=400,
                    detail="Email column exists but contains no valid email addresses"
                )
            
            # Si nous arrivons ici, nous avons une colonne 'email' valide
            logger.info("Valid email column confirmed")
            
            # Afficher les premières lignes pour débogage
            logger.info(f"First few rows: {df.head(2).to_dict('records')}")
            
            # Créer un générateur d'emails personnalisé si les infos utilisateur sont fournies
            if your_name or your_position or company_name:
                logger.info("Creating custom email generator with user parameters")
                email_generator = ProspectEmailGenerator(
                    your_name=your_name,
                    your_position=your_position,
                    company_name=company_name,
                    your_contact=your_contact
                )
            else:
                email_generator = ProspectEmailGenerator()
            
            # Récupérer le template si nécessaire
            template = None
            if not use_ai and template_id:
                template = db.query(Template).filter(Template.id == template_id).first()
                if not template:
                    raise HTTPException(status_code=404, detail="Template not found")
            
            # Générer les emails
            generated_emails = []
            saved_emails = []
            
            # Vérifier les emails déjà partagés par des amis
            shared_emails_query = db.query(SharedEmails.contact_email).all()
            shared_emails = {email[0] for email in shared_emails_query}
            
            for _, row in df.iterrows():
                # Skip if email is in shared cache
                if row['email'] in shared_emails:
                    logger.info(f"Skipping {row['email']} - in shared cache")
                    continue
                    
                # Check if email already exists in the database for this stage
                existing_email = db.query(EmailStatus).filter(
                    EmailStatus.email == row['email'],
                    EmailStatus.stage == stage
                ).first()
                
                if existing_email:
                    # Use existing email
                    saved_emails.append({
                        "id": existing_email.id,
                        "to": existing_email.email,
                        "subject": existing_email.subject,
                        "body": existing_email.body,
                        "stage": existing_email.stage,
                        "status": existing_email.status
                    })
                    continue
                
                # Generate email content
                prospect_info = {
                    'first_name': row.get('first_name', ''),
                    'last_name': row.get('last_name', ''),
                    'company': row.get('company', ''),
                    'position': row.get('position', ''),
                    'industry': row.get('industry', ''),
                    'technologies': row.get('technologies', '')
                }
                
                # Save or update contact info
                contact = db.query(Contact).filter(Contact.email == row['email']).first()
                if not contact:
                    contact = Contact(
                        email=row['email'],
                        first_name=prospect_info.get('first_name', ''),
                        last_name=prospect_info.get('last_name', ''),
                        company=prospect_info.get('company', ''),
                        position=prospect_info.get('position', ''),
                        industry=prospect_info.get('industry', ''),
                        technologies=prospect_info.get('technologies', '')
                    )
                    db.add(contact)
                
                if use_ai:
                    # Generate with AI
                    email_content = email_generator.generate_email_content_with_ai(
                        prospect_info, 
                        stage=stage
                    )
                elif template:
                    # Generate from template
                    email_content = email_generator.generate_from_template(
                        prospect_info,
                        template.subject,
                        template.body
                    )
                else:
                    # Use default template
                    email_content = email_generator.generate_email_content(prospect_info)
                
                # Créer un nouvel email dans la base de données
                new_email = EmailStatus(
                    email=row['email'],
                    stage=stage,
                    status='draft',
                    subject=email_content['subject'],
                    body=email_content['body']
                )
                db.add(new_email)
                db.commit()
                db.refresh(new_email)
                
                # Ajouter à la liste des emails générés
                generated_emails.append({
                    "id": new_email.id,
                    "to": row['email'],
                    "subject": email_content['subject'],
                    "body": email_content['body'],
                    "stage": stage,
                    "status": "draft"
                })
            
            # Commit changes to database
            db.commit()
            
            # Combine generated and saved emails
            all_emails = generated_emails + saved_emails
            
            return {"emails": all_emails}
            
        except Exception as e:
            logger.error(f"Error generating emails: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error generating emails: {str(e)}"
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only CSV files are accepted."
        )

@router.get("/by-stage/{stage}")
async def get_emails_by_stage(
    stage: str,
    db: Session = Depends(get_db)
):
    """
    Get all emails for a specific stage (outreach, followup, lastchance)
    """
    valid_stages = ['outreach', 'followup', 'lastchance']
    if stage not in valid_stages:
        raise HTTPException(status_code=400, detail="Invalid stage. Must be one of: outreach, followup, lastchance")
    
    emails = db.query(EmailStatus).filter(EmailStatus.stage == stage).all()
    
    result = []
    for email in emails:
        result.append({
            "id": email.id,
            "to": email.email,
            "subject": email.subject,
            "body": email.body,
            "stage": email.stage,
            "status": email.status,
            "sent_at": email.sent_at
        })
    
    return result

@router.put("/{email_id}/status")
async def update_email_status(
    email_id: int,
    status: dict,
    db: Session = Depends(get_db)
):
    """
    Update the status of an email (sent, opened, replied, bounced)
    """
    email = db.query(EmailStatus).filter(EmailStatus.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    valid_statuses = ['draft', 'sent', 'opened', 'replied', 'bounced']
    if status.get('status') not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
    
    # Update the status and the corresponding timestamp
    new_status = status.get('status')
    email.status = new_status
    
    if new_status == 'sent':
        email.sent_at = datetime.utcnow()
    elif new_status == 'opened':
        email.opened_at = datetime.utcnow()
    elif new_status == 'replied':
        email.replied_at = datetime.utcnow()
    elif new_status == 'bounced':
        email.bounced_at = datetime.utcnow()
    
    db.commit()
    db.refresh(email)
    
    return {
        "id": email.id,
        "to": email.email,
        "subject": email.subject,
        "status": email.status,
        "stage": email.stage
    }

@router.put("/{email_id}/stage")
async def update_email_stage(
    email_id: int,
    stage: dict,
    db: Session = Depends(get_db)
):
    """
    Update the stage of an email (outreach, followup, lastchance)
    """
    email = db.query(EmailStatus).filter(EmailStatus.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    valid_stages = ['outreach', 'followup', 'lastchance']
    if stage.get('stage') not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}")
    
    # Check if this recipient already has an email in the target stage
    existing = db.query(EmailStatus).filter(
        EmailStatus.email == email.email,
        EmailStatus.stage == stage.get('stage')
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"This recipient already has an email in the {stage.get('stage')} stage")
    
    # Update the stage
    email.stage = stage.get('stage')
    email.status = 'draft'  # Reset status when changing stage
    email.sent_at = None
    
    db.commit()
    db.refresh(email)
    
    return {
        "id": email.id,
        "to": email.email,
        "subject": email.subject,
        "status": email.status,
        "stage": email.stage
    }

@router.get("/templates", response_model=List[Dict[str, Any]])
async def get_templates(
    db: Session = Depends(get_db)
):
    """
    Récupère tous les templates d'email
    """
    templates = db.query(Template).all()
    
    result = []
    for template in templates:
        result.append({
            "id": template.id,
            "name": template.name,
            "subject": template.subject,
            "body": template.body,
            "is_default": template.is_default,
            "created_at": template.created_at.isoformat() if template.created_at else None
        })
    
    return result

@router.get("/templates/{template_id}", response_model=Dict[str, Any])
async def get_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    """
    Récupère un template d'email par son ID
    """
    template = db.query(Template).filter(Template.id == template_id).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return {
        "id": template.id,
        "name": template.name,
        "subject": template.subject,
        "body": template.body,
        "is_default": template.is_default,
        "created_at": template.created_at.isoformat() if template.created_at else None
    }

@router.put("/templates/{template_id}", response_model=Dict[str, Any])
async def update_template(
    template_id: int,
    template: EmailTemplate,
    db: Session = Depends(get_db)
):
    """
    Met à jour un template d'email
    """
    db_template = db.query(Template).filter(Template.id == template_id).first()
    
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Mettre à jour les champs
    db_template.name = template.name
    db_template.subject = template.subject
    db_template.body = template.body
    
    # Gérer le status par défaut
    if template.is_default and not db_template.is_default:
        # Définir tous les autres templates comme non-défaut
        default_templates = db.query(Template).filter(Template.is_default == True).all()
        for dt in default_templates:
            dt.is_default = False
    
    db_template.is_default = template.is_default
    
    # Sauvegarder les changements
    db.commit()
    db.refresh(db_template)
    
    return {
        "id": db_template.id,
        "name": db_template.name,
        "subject": db_template.subject,
        "body": db_template.body,
        "is_default": db_template.is_default,
        "created_at": db_template.created_at.isoformat() if db_template.created_at else None
    }

@router.delete("/templates/{template_id}", response_model=Dict[str, Any])
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    """
    Supprime un template d'email
    """
    template = db.query(Template).filter(Template.id == template_id).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Ne pas supprimer le template par défaut
    if template.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete default template")
    
    # Supprimer les références au template
    emails = db.query(EmailStatus).filter(EmailStatus.template_id == template_id).all()
    for email in emails:
        email.template_id = None
    
    # Supprimer le template
    db.delete(template)
    db.commit()
    
    return {"success": True, "message": "Template deleted successfully"}

@router.post("/templates", response_model=EmailTemplate)
async def save_template(
    template: EmailTemplate,
    db: Session = Depends(get_db)
):
    """
    Sauvegarde un nouveau template d'email
    """
    # Créer le nouveau template
    new_template = Template(
        name=template.name,
        subject=template.subject,
        body=template.body,
        is_default=template.is_default,
        user_id=1  # Temporaire: obtenir l'ID de l'utilisateur actuel
    )
    
    # Définir tous les autres templates comme non-défaut si celui-ci est le défaut
    if template.is_default:
        default_templates = db.query(Template).filter(Template.is_default == True).all()
        for dt in default_templates:
            dt.is_default = False
        db.commit()
    
    # Ajouter à la base de données
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    
    return EmailTemplate(
        name=new_template.name,
        subject=new_template.subject,
        body=new_template.body,
        is_default=new_template.is_default
    )

@router.get("/cache", response_model=CacheInfo)
async def get_cache_info():
    """
    Récupère des informations sur le cache d'emails
    """
    cache_size = len(email_generator.cache)
    last_updated = max([entry.get('timestamp', '') for entry in email_generator.cache.values()]) if cache_size > 0 else None
    
    return CacheInfo(
        size=cache_size,
        last_updated=last_updated,
        cache_file=email_generator.cache_file
    )

@router.delete("/cache", response_model=Dict[str, Any])
async def clear_cache():
    """
    Vide le cache d'emails
    """
    email_generator.cache = {}
    
    # Sauvegarder le cache vide
    with open(email_generator.cache_file, 'w', encoding='utf-8') as f:
        json.dump({}, f)
    
    return {"success": True, "message": "Cache vidé avec succès"} 