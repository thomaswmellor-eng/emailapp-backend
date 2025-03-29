import os
from pydantic import BaseSettings, validator
from typing import List, Union
from dotenv import load_dotenv

# Charger les variables d'environnement du fichier .env
load_dotenv()

class Settings(BaseSettings):
    # Base de données
    DB_CONNECTION_STRING: str = os.getenv("DB_CONNECTION_STRING", "sqlite:///./emailapp.db")
    
    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")
    
    # Azure Storage Blob pour les fichiers
    AZURE_STORAGE_CONNECTION_STRING: str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    BLOB_CONTAINER_NAME: str = os.getenv("BLOB_CONTAINER_NAME", "emailfiles")
    
    # Mode de déploiement
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")  # development, production
    
    # Autres paramètres
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")  # Clé OpenAI standard (non-Azure)
    CACHE_FILE: str = os.getenv("CACHE_FILE", "email_cache.json")
    
    # CORS settings - valeur par défaut pour accepter les requêtes locales
    CORS_ORIGINS: Union[List[str], str] = "*"
    
    @validator("CORS_ORIGINS", pre=True)
    def parse_cors_origins(cls, v):
        # Si c'est déjà une liste, la renvoyer telle quelle
        if isinstance(v, list):
            return v
        
        # Si c'est une chaîne "*", autoriser toutes les origines
        if v == "*":
            return ["*"]
        
        # Sinon, diviser la chaîne en liste
        if isinstance(v, str):
            try:
                return [origin.strip() for origin in v.split(",") if origin.strip()]
            except Exception:
                # En cas d'erreur, autoriser toutes les origines
                return ["*"]
        
        # Si aucun des cas ci-dessus ne s'applique, autoriser toutes les origines
        return ["*"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        # Rendre le chargement des variables d'environnement insensible à la casse
        case_sensitive = False

# Créer une instance de Settings
try:
    settings = Settings()
except Exception as e:
    print(f"Erreur lors du chargement des paramètres: {e}")
    # Valeurs par défaut en cas d'erreur
    class DefaultSettings:
        DB_CONNECTION_STRING = "sqlite:///./emailapp.db"
        ENVIRONMENT = "development"
        CORS_ORIGINS = ["*"]  # Autoriser toutes les origines par défaut

    settings = DefaultSettings()

# Determine whether to use Azure OpenAI or standard OpenAI
def use_azure_openai():
    return settings.ENVIRONMENT == "production" and settings.AZURE_OPENAI_API_KEY != "" 