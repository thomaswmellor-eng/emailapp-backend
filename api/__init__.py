# Ce fichier initialise le package api
# Laisser ce fichier vide pour éviter les problèmes d'importation

from .email_routes import router as email_router
from .friends_routes import router as friends_router
from .template_routes import router as template_router
from .auth_routes import router as auth_router
