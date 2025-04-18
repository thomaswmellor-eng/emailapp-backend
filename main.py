import os
import logging
from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from fastapi.responses import JSONResponse
import sys
from api import auth_routes, user_routes, contact_routes, template_routes, email_routes, friend_routes, admin_routes
from models.database import create_tables
from config import settings

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

# Charger les variables d'environnement
load_dotenv()

# Créer l'application FastAPI
app = FastAPI(
    title="Email Generator API",
    description="API pour générer des emails personnalisés à partir de contacts",
    version="1.0.0"
)

# Configurer CORS pour permettre les requêtes du frontend
cors_origins = settings.CORS_ORIGINS
logger.info(f"Configuration CORS - Origines autorisées: {cors_origins}")

# Si on a juste ['*'], accepter toutes les origines
if cors_origins == ["*"]:
    logger.info("Mode CORS permissif activé - Toutes les origines sont autorisées")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Mode restrictif avec origines spécifiques
    logger.info(f"Mode CORS restrictif activé - Origines autorisées: {cors_origins}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Initialize the database
create_tables()

# Inclure les routes
app.include_router(auth_routes.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(user_routes.router, prefix="/api/users", tags=["Users"])
app.include_router(contact_routes.router, prefix="/api/contacts", tags=["Contacts"])
app.include_router(template_routes.router, prefix="/api/templates", tags=["Templates"])
app.include_router(email_routes.router, prefix="/api/emails", tags=["Emails"])
app.include_router(friend_routes.router, prefix="/api/friends", tags=["Friends"])
app.include_router(admin_routes.router, prefix="/api/admin", tags=["Administration"])

# Gestionnaire d'exceptions global
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Erreur non gérée: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Une erreur s'est produite: {str(exc)}"}
    )

@app.get("/api/health")
async def health_check():
    """
    Point de terminaison pour vérifier l'état de l'API
    """
    return {"status": "ok", "version": "1.0.0", "environment": settings.ENVIRONMENT}

@app.get("/api/config")
async def check_config():
    """
    Point de terminaison pour vérifier la configuration de l'API
    """
    # Vérifier les variables d'environnement Azure OpenAI
    azure_config = {
        "api_key_set": bool(os.getenv("AZURE_OPENAI_API_KEY")),
        "endpoint_set": bool(os.getenv("AZURE_OPENAI_ENDPOINT")),
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
        "deployment_name": os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
    }
    
    # Masquer la clé API
    if azure_config["api_key_set"]:
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_config["api_key_prefix"] = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
    
    return {
        "azure_openai": azure_config,
        "sender_info": {
            "company_name": os.getenv("COMPANY_NAME", "Non défini"),
            "your_name": os.getenv("YOUR_NAME", "Non défini"),
            "your_position": os.getenv("YOUR_POSITION", "Non défini"),
            "your_contact": os.getenv("YOUR_CONTACT", "Non défini"),
        }
    }

@app.get("/")
async def root():
    """
    Racine de l'API
    """
    return {
        "message": "Bienvenue sur l'API de génération d'emails",
        "docs": "/docs",
        "environment": settings.ENVIRONMENT
    }

@app.get("/debug/cors")
async def debug_cors():
    """
    Point de terminaison pour déboguer la configuration CORS
    """
    cors_origins = settings.CORS_ORIGINS
    
    # Vérifier si chaque origine est correctement formatée
    validated_origins = []
    for origin in cors_origins:
        origin = origin.strip()
        if origin == "*":
            validated_origins.append({"origin": "*", "status": "valid"})
        elif origin.startswith(("http://", "https://")):
            validated_origins.append({"origin": origin, "status": "valid"})
        else:
            validated_origins.append({"origin": origin, "status": "invalid", "reason": "missing scheme (http:// or https://)"})
    
    return {
        "configured_origins": cors_origins,
        "environment_variable": os.getenv("CORS_ORIGINS", "NOT_SET"),
        "validated_origins": validated_origins
    }

# Initialiser la base de données au démarrage
@app.on_event("startup")
async def startup_event():
    logger.info(f"Démarrage de l'application en mode {settings.ENVIRONMENT}")
    
    # Initialiser la base de données
    create_tables()
    logger.info("Base de données initialisée")
    
    # Afficher la configuration actuelle
    logger.info(f"URL de la base de données: {settings.DB_CONNECTION_STRING.split('://')[-1]}")
    logger.info(f"Azure OpenAI endpoint: {settings.AZURE_OPENAI_ENDPOINT or 'Non configuré'}")
    
    if settings.ENVIRONMENT == "production":
        logger.info("Mode production activé")
        if not settings.AZURE_OPENAI_API_KEY:
            logger.warning("Azure OpenAI API key non configurée en production")
    else:
        logger.info("Mode développement activé")
        if not settings.OPENAI_API_KEY:
            logger.warning("OpenAI API key standard non configurée")

if __name__ == "__main__":
    logger.info("Démarrage du serveur...")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True) 