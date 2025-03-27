import os
from pydantic import BaseSettings
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
    
    # CORS settings
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "*").split(",")
    
    class Config:
        env_file = ".env"

settings = Settings()

# Determine whether to use Azure OpenAI or standard OpenAI
def use_azure_openai():
    return settings.ENVIRONMENT == "production" and settings.AZURE_OPENAI_API_KEY != "" 