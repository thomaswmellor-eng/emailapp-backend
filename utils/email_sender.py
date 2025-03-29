import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Configurer les paramètres SMTP depuis les variables d'environnement ou utiliser des valeurs par défaut
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@emailgenerator.com")
DEFAULT_FROM_NAME = os.getenv("DEFAULT_FROM_NAME", "Email Generator")

class EmailSender:
    """
    Classe pour envoyer des emails
    """
    
    @staticmethod
    def send_email(to_email, subject, html_content, from_email=None, from_name=None):
        """
        Envoie un email au destinataire spécifié
        
        Args:
            to_email (str): Adresse email du destinataire
            subject (str): Sujet de l'email
            html_content (str): Contenu HTML de l'email
            from_email (str, optional): Adresse email de l'expéditeur. Par défaut: DEFAULT_FROM_EMAIL
            from_name (str, optional): Nom de l'expéditeur. Par défaut: DEFAULT_FROM_NAME
            
        Returns:
            bool: True si l'email a été envoyé avec succès, False sinon
        """
        if not from_email:
            from_email = DEFAULT_FROM_EMAIL
        
        if not from_name:
            from_name = DEFAULT_FROM_NAME
            
        # Créer le message
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = f"{from_name} <{from_email}>"
        msg['To'] = to_email
        
        # Ajouter le contenu HTML
        msg.attach(MIMEText(html_content, 'html'))
        
        try:
            # Connexion au serveur SMTP
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.ehlo()
            server.starttls()
            
            # Authentification si les identifiants sont fournis
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                
            # Envoi de l'email
            server.sendmail(from_email, to_email, msg.as_string())
            server.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False
    
    @staticmethod
    def send_verification_code(to_email, code):
        """
        Envoie un code de vérification par email
        
        Args:
            to_email (str): Adresse email du destinataire
            code (str): Code de vérification à envoyer
            
        Returns:
            bool: True si l'email a été envoyé avec succès, False sinon
        """
        subject = "Code de vérification - Email Generator"
        
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 10px; text-align: center; }}
                .content {{ padding: 20px; border: 1px solid #ddd; }}
                .code {{ font-size: 24px; font-weight: bold; text-align: center; 
                         padding: 10px; margin: 20px 0; background-color: #f5f5f5; }}
                .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #777; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Email Generator</h2>
                </div>
                <div class="content">
                    <p>Bonjour,</p>
                    <p>Voici votre code de vérification pour accéder à l'application Email Generator :</p>
                    <div class="code">{code}</div>
                    <p>Ce code est valable pendant 15 minutes.</p>
                    <p>Si vous n'avez pas demandé ce code, veuillez ignorer cet email.</p>
                </div>
                <div class="footer">
                    <p>Cet email a été envoyé automatiquement, merci de ne pas y répondre.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return EmailSender.send_email(to_email, subject, html_content) 