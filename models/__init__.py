# Ce fichier permet de rendre le répertoire 'models' importable
# Il importera les modèles dans la portée du module

from .email_models import (
    ContactInfo,
    EmailContent,
    EmailGenerationResponse,
    EmailTemplate,
    CacheInfo,
    UserProfile
)
