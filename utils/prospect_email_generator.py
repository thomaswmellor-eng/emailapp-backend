import os
import csv
import json
import logging
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd
import openai
from dotenv import load_dotenv
import random
import re
from config import settings, use_azure_openai

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("email_generator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("email_generator")

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import AzureAICredential
    AZURE_AI_INFERENCE_AVAILABLE = True
except ImportError:
    AZURE_AI_INFERENCE_AVAILABLE = False
    logger.warning("azure-ai-inference not available, attempting to install it...")
    try:
        import subprocess
        subprocess.run(["pip", "install", "azure-ai-inference==1.0.0b9"], check=True)
        from azure.ai.inference import ChatCompletionsClient
        from azure.ai.inference.models import AzureAICredential
        AZURE_AI_INFERENCE_AVAILABLE = True
    except Exception as e:
        logger.error(f"Failed to install azure-ai-inference: {e}")

def generate_email_content_with_ai(prospect_info, stage="outreach", api_type="azure"):
    """Generate email content using Azure OpenAI API"""
    
    # Récupérer les informations d'environnement
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-11-20")
    
    # Vérifier que les informations nécessaires sont disponibles
    if not api_key or not endpoint or not deployment_name:
        logger.error("Azure OpenAI API credentials not found in environment variables")
        return {
            "subject": f"Outreach to {prospect_info.get('first_name', '')} {prospect_info.get('last_name', '')}",
            "body": f"[Error generating content: Azure OpenAI API credentials not configured]"
        }
    
    # Construire un prompt basé sur les informations du prospect et l'étape
    if stage == "outreach":
        prompt_type = "initial outreach"
    elif stage == "followup":
        prompt_type = "follow-up message after a few days of no response"
    else:  # lastchance
        prompt_type = "final follow-up (last chance) email"
    
    # Vérifier que le client a fourni un nom/entreprise
    your_name = os.environ.get("YOUR_NAME", "Your Name")
    your_position = os.environ.get("YOUR_POSITION", "Your Position")
    company_name = os.environ.get("COMPANY_NAME", "Your Company")
    
    system_message = f"""You are an expert sales email writer. Write professional, personalized sales emails that are:
1. Concise (5-7 sentences max)
2. Focused on value and recipient's needs
3. Conversational but professional
4. Include a clear and simple call to action
5. Not overly pushy or salesy
6. Tailored to the prospect's industry and position"""
    
    prompt = f"""Write a personalized {prompt_type} email to {prospect_info.get('first_name', '')} {prospect_info.get('last_name', '')} 
who works as {prospect_info.get('position', 'a professional')} at {prospect_info.get('company', 'their company')}.

Their industry is: {prospect_info.get('industry', 'technology')}
Technologies they use: {prospect_info.get('technologies', 'various software solutions')}

The email should be from {your_name}, {your_position} at {company_name}.

Format your response as a JSON object with 'subject' and 'body' fields (no other fields). 
Do not include any explanation or additional text outside the JSON.

Example format:
```json
{{
  "subject": "Subject line here",
  "body": "Email body here with appropriate line breaks."
}}
```"""
    
    try:
        if AZURE_AI_INFERENCE_AVAILABLE:
            logger.info("Using Azure AI Inference API")
            client = ChatCompletionsClient(endpoint, AzureAICredential(api_key))
            
            response = client.complete(
                deployment=deployment_name,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            content = response.choices[0].message.content
        else:
            # Fallback to standard OpenAI client
            logger.info("Using standard OpenAI client with Azure settings")
            
            openai.api_type = "azure"
            openai.api_key = api_key
            openai.api_base = endpoint
            openai.api_version = api_version
            
            response = openai.ChatCompletion.create(
                engine=deployment_name,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            content = response.choices[0].message.content
        
        # Extraire le JSON de la réponse
        # Parfois l'API peut retourner le JSON encadré par ```json et ``` ou juste {}
        if '```json' in content:
            json_str = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            json_str = content.split('```')[1].split('```')[0].strip()
        else:
            json_str = content.strip()
        
        logger.info("Successfully generated email content")
        email_content = json.loads(json_str)
        return email_content
        
    except Exception as e:
        logger.error(f"Error generating email with AI: {str(e)}")
        return {
            "subject": f"Outreach to {prospect_info.get('first_name', '')} {prospect_info.get('last_name', '')}",
            "body": f"Hello {prospect_info.get('first_name', '')},\n\nI noticed that {prospect_info.get('company', 'your company')} is doing interesting work in the {prospect_info.get('industry', 'technology')} industry. I'd love to connect and discuss how we might be able to help with your {prospect_info.get('technologies', 'technology')} needs.\n\nWould you be available for a quick call next week?\n\nBest regards,\n{your_name}\n{your_position}, {company_name}"
        }

class ProspectEmailGenerator:
    def __init__(self, 
                 your_name: str = "John Doe", 
                 your_position: str = "Sales Representative", 
                 company_name: str = "ACME Corp",
                 your_contact: str = "john.doe@example.com",
                 cache_file: str = None):
        """
        Initialise le générateur d'emails avec les informations de l'expéditeur
        """
        self.your_name = your_name
        self.your_position = your_position
        self.company_name = company_name
        self.your_contact = your_contact
        
        # Utiliser le cache spécifié ou celui par défaut
        self.cache_file = cache_file or settings.CACHE_FILE
        
        # Si le fichier de cache n'existe pas, créer un cache vide
        self.cache = {}
        
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except Exception as e:
                logger.error(f"Erreur lors de la lecture du cache: {str(e)}")
                self.cache = {}
        else:
            # Créer un fichier de cache vide
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def replace_variables(self, template: str, variables: Dict[str, str]) -> str:
        """
        Remplace les variables dans un modèle d'email.
        Les variables sont au format {{variable_name}}.
        """
        # Ajouter les informations de l'expéditeur aux variables
        all_vars = {
            'your_name': self.your_name,
            'your_position': self.your_position,
            'company_name': self.company_name,
            'your_contact': self.your_contact,
            **variables
        }
        
        # Remplacer les variables dans le template
        for var, value in all_vars.items():
            template = template.replace("{{" + var + "}}", value or "")
        
        return template

    def generate_email_content(self, prospect_info: Dict[str, str], stage: str = "outreach") -> Dict[str, str]:
        """
        Génère le contenu d'un email à partir d'informations sur le prospect
        """
        # Vérifier si l'email est déjà dans le cache
        email = prospect_info.get('email', '')
        if email in self.cache:
            logger.info(f"Email trouvé dans le cache: {email}")
            return {
                'subject': self.cache[email].get('subject', ''),
                'body': self.cache[email].get('body', '')
            }
        
        # Génère un email basé sur le stage et les informations du prospect
        default_templates = {
            "outreach": {
                "subject": "Opportunité de collaboration",
                "body": """Bonjour {{first_name}},

J'espère que ce message vous trouve bien. Je suis {{your_name}} de {{company_name}}.

Nous aidons des entreprises comme {{company}} à améliorer leurs processus de vente et j'ai pensé que cela pourrait vous intéresser, étant donné votre rôle de {{position}}.

Seriez-vous disponible pour un court appel cette semaine afin que je puisse vous présenter comment nous pourrions vous aider ?

Cordialement,
{{your_name}}
{{your_position}} | {{company_name}}
{{your_contact}}"""
            },
            "followup": {
                "subject": "Re: Opportunité de collaboration",
                "body": """Bonjour {{first_name}},

Je voulais simplement faire un suivi concernant mon précédent message. 

J'aimerais vraiment discuter de la façon dont {{company_name}} pourrait aider {{company}} à atteindre ses objectifs commerciaux.

Seriez-vous disponible pour un court appel dans les prochains jours ?

Cordialement,
{{your_name}}
{{your_position}} | {{company_name}}
{{your_contact}}"""
            },
            "lastchance": {
                "subject": "Dernière chance - Opportunité pour {{company}}",
                "body": """Bonjour {{first_name}},

Je vous ai contacté récemment concernant une opportunité qui pourrait être intéressante pour {{company}}.

C'est ma dernière tentative de contact. Si vous êtes intéressé par une discussion, n'hésitez pas à me répondre à ce message.

Cordialement,
{{your_name}}
{{your_position}} | {{company_name}}
{{your_contact}}"""
            }
        }
        
        # Utiliser le template par défaut si le stage n'est pas reconnu
        if stage not in default_templates:
            stage = "outreach"
        
        template = default_templates[stage]
        subject = self.replace_variables(template["subject"], prospect_info)
        body = self.replace_variables(template["body"], prospect_info)
        
        # Sauvegarder dans le cache
        self.cache[email] = {
            'subject': subject,
            'body': body,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du cache: {str(e)}")
        
        return {
            'subject': subject,
            'body': body
        }
    
    def generate_from_template(self, prospect_info: Dict[str, str], subject_template: str, body_template: str) -> Dict[str, str]:
        """
        Génère le contenu d'un email à partir d'un template personnalisé
        """
        subject = self.replace_variables(subject_template, prospect_info)
        body = self.replace_variables(body_template, prospect_info)
        
        # Sauvegarder dans le cache si un email est fourni
        email = prospect_info.get('email', '')
        if email:
            self.cache[email] = {
                'subject': subject,
                'body': body,
                'timestamp': datetime.now().isoformat()
            }
            
            try:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Erreur lors de la sauvegarde du cache: {str(e)}")
        
        return {
            'subject': subject,
            'body': body
        }
    
    def generate_email_content_with_ai(self, prospect_info: Dict[str, str], stage: str = "outreach") -> Dict[str, str]:
        """
        Génère le contenu d'un email avec l'aide de l'IA en fonction des informations du prospect
        """
        # Vérifier si l'email est déjà dans le cache
        email = prospect_info.get('email', '')
        if email in self.cache:
            logger.info(f"Email trouvé dans le cache: {email}")
            return {
                'subject': self.cache[email].get('subject', ''),
                'body': self.cache[email].get('body', '')
            }
            
        # Déterminer si on utilise Azure OpenAI ou OpenAI standard
        if use_azure_openai():
            # Configuration d'Azure OpenAI
            logger.info("Utilisation d'Azure OpenAI")
            from azure.ai.openai import AzureOpenAI
            
            client = AzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY, 
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT, 
                api_version="2023-12-01-preview"
            )
        else:
            # Configuration d'OpenAI standard
            logger.info("Utilisation d'OpenAI standard")
            openai.api_key = settings.OPENAI_API_KEY
        
        # Préparation du prompt pour l'IA
        first_name = prospect_info.get('first_name', 'prospect')
        position = prospect_info.get('position', 'professional')
        company = prospect_info.get('company', 'company')
        industry = prospect_info.get('industry', '')
        technologies = prospect_info.get('technologies', '')
        
        stages_descriptions = {
            "outreach": "un premier contact",
            "followup": "un suivi après un premier email sans réponse",
            "lastchance": "une dernière tentative de contact après plusieurs suivis sans réponse"
        }
        
        stage_desc = stages_descriptions.get(stage, "un premier contact")
        
        # Construire le prompt pour l'IA
        prompt = f"""
Je suis {self.your_name}, {self.your_position} chez {self.company_name}. 
Je dois rédiger un email professionnel pour {stage_desc} avec un prospect nommé {first_name} qui travaille comme {position} pour {company}.
"""

        if industry:
            prompt += f"La société est dans l'industrie: {industry}. "
            
        if technologies:
            prompt += f"Et ils utilisent les technologies suivantes: {technologies}. "
        
        prompt += f"""
Écrivez uniquement l'email complet (objet et corps), directement utilisable. 
L'email doit être personnalisé, professionnel et concis (max 150 mots).
Format souhaité:
Objet: [Le sujet de l'email]

[Corps de l'email]

[Signature professionnelle incluant mon nom ({self.your_name}), poste ({self.your_position}), société ({self.company_name}) et contact ({self.your_contact})]
"""

        try:
            if use_azure_openai():
                # Appel à Azure OpenAI
                response = client.chat.completions.create(
                    model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                    messages=[
                        {"role": "system", "content": "Vous êtes un rédacteur professionnel d'emails de prospection."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                completion_text = response.choices[0].message.content.strip()
            else:
                # Appel à OpenAI standard
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Vous êtes un rédacteur professionnel d'emails de prospection."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                completion_text = response.choices[0].message['content'].strip()
                
            # Extraire le sujet et le corps de l'email
            subject_match = re.search(r'Objet: (.+?)(?:\n|$)', completion_text)
            subject = subject_match.group(1) if subject_match else "Opportunité de collaboration"
            
            # Le corps est tout le reste après "Objet: ..."
            if subject_match:
                body_start = subject_match.end()
                body = completion_text[body_start:].strip()
            else:
                body = completion_text
            
            # Sauvegarder dans le cache
            if email:
                self.cache[email] = {
                    'subject': subject,
                    'body': body,
                    'timestamp': datetime.now().isoformat()
                }
                
                try:
                    with open(self.cache_file, 'w', encoding='utf-8') as f:
                        json.dump(self.cache, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.error(f"Erreur lors de la sauvegarde du cache: {str(e)}")
            
            return {
                'subject': subject,
                'body': body
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la génération par IA: {str(e)}")
            # Fallback to template generation in case of error
            return self.generate_email_content(prospect_info, stage)
    
    def is_email_in_shared_cache(self, email: str, shared_emails: List[str]) -> bool:
        """
        Vérifie si un email est dans le cache partagé par des amis
        """
        return email in shared_emails
        
    def clear_cache(self):
        """
        Vide le cache d'emails
        """
        self.cache = {}
        
        # Sauvegarder le cache vide
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump({}, f)

# Fonction à appeler directement sans instance de classe
def generate_email_content_with_ai(
    prospect_info: Dict[str, str], 
    your_name: str = "John Doe", 
    your_position: str = "Sales Representative", 
    company_name: str = "ACME Corp",
    your_contact: str = "john.doe@example.com",
    stage: str = "outreach"
) -> Dict[str, str]:
    """
    Fonction utilitaire pour générer un email avec IA sans instancier la classe
    """
    generator = ProspectEmailGenerator(
        your_name=your_name,
        your_position=your_position,
        company_name=company_name,
        your_contact=your_contact
    )
    
    return generator.generate_email_content_with_ai(prospect_info, stage)

def generate_email_content_with_template(prospect_info, stage="outreach", api_type="azure"):
    """Generate email content using Azure OpenAI API"""
    
    # Récupérer les informations d'environnement
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-11-20")
    
    # Vérifier que les informations nécessaires sont disponibles
    if not api_key or not endpoint or not deployment_name:
        logger.error("Azure OpenAI API credentials not found in environment variables")
        return {
            "subject": f"Outreach to {prospect_info.get('first_name', '')} {prospect_info.get('last_name', '')}",
            "body": f"[Error generating content: Azure OpenAI API credentials not configured]"
        }
    
    # Construire un prompt basé sur les informations du prospect et l'étape
    if stage == "outreach":
        prompt_type = "initial outreach"
    elif stage == "followup":
        prompt_type = "follow-up message after a few days of no response"
    else:  # lastchance
        prompt_type = "final follow-up (last chance) email"
    
    # Vérifier que le client a fourni un nom/entreprise
    your_name = os.environ.get("YOUR_NAME", "Your Name")
    your_position = os.environ.get("YOUR_POSITION", "Your Position")
    company_name = os.environ.get("COMPANY_NAME", "Your Company")
    
    system_message = f"""You are an expert sales email writer. Write professional, personalized sales emails that are:
1. Concise (5-7 sentences max)
2. Focused on value and recipient's needs
3. Conversational but professional
4. Include a clear and simple call to action
5. Not overly pushy or salesy
6. Tailored to the prospect's industry and position"""
    
    prompt = f"""Write a personalized {prompt_type} email to {prospect_info.get('first_name', '')} {prospect_info.get('last_name', '')} 
who works as {prospect_info.get('position', 'a professional')} at {prospect_info.get('company', 'their company')}.

Their industry is: {prospect_info.get('industry', 'technology')}
Technologies they use: {prospect_info.get('technologies', 'various software solutions')}

The email should be from {your_name}, {your_position} at {company_name}.

Format your response as a JSON object with 'subject' and 'body' fields (no other fields). 
Do not include any explanation or additional text outside the JSON.

Example format:
```json
{{
  "subject": "Subject line here",
  "body": "Email body here with appropriate line breaks."
}}
```"""
    
    try:
        if AZURE_AI_INFERENCE_AVAILABLE:
            logger.info("Using Azure AI Inference API")
            client = ChatCompletionsClient(endpoint, AzureAICredential(api_key))
            
            response = client.complete(
                deployment=deployment_name,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            content = response.choices[0].message.content
        else:
            # Fallback to standard OpenAI client
            logger.info("Using standard OpenAI client with Azure settings")
            
            openai.api_type = "azure"
            openai.api_key = api_key
            openai.api_base = endpoint
            openai.api_version = api_version
            
            response = openai.ChatCompletion.create(
                engine=deployment_name,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            content = response.choices[0].message.content
        
        # Extraire le JSON de la réponse
        # Parfois l'API peut retourner le JSON encadré par ```json et ``` ou juste {}
        if '```json' in content:
            json_str = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            json_str = content.split('```')[1].split('```')[0].strip()
        else:
            json_str = content.strip()
        
        logger.info("Successfully generated email content")
        email_content = json.loads(json_str)
        return email_content
        
    except Exception as e:
        logger.error(f"Error generating email with AI: {str(e)}")
        return {
            "subject": f"Outreach to {prospect_info.get('first_name', '')} {prospect_info.get('last_name', '')}",
            "body": f"Hello {prospect_info.get('first_name', '')},\n\nI noticed that {prospect_info.get('company', 'your company')} is doing interesting work in the {prospect_info.get('industry', 'technology')} industry. I'd love to connect and discuss how we might be able to help with your {prospect_info.get('technologies', 'technology')} needs.\n\nWould you be available for a quick call next week?\n\nBest regards,\n{your_name}\n{your_position}, {company_name}"
        }

class ProspectEmailGenerator:
    def __init__(self, cache_file="email_cache.json", your_name=None, your_position=None, company_name=None, your_contact=None):
        """
        Initialise le générateur d'emails pour les prospects.
        
        Args:
            cache_file (str): Chemin vers le fichier de cache
            your_name (str): Nom de l'expéditeur
            your_position (str): Poste de l'expéditeur
            company_name (str): Nom de la société de l'expéditeur
            your_contact (str): Contact de l'expéditeur
        """
        logger.info("Initialisation du générateur d'emails")
        
        # Charger les variables d'environnement
        load_dotenv()
        
        # Configurer l'API d'OpenAI
        self.api_key = os.getenv('AZURE_OPENAI_API_KEY')
        self.api_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        self.deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME')
        self.azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
  
        
        
        # Informations d'expéditeur
        self.company_name = company_name or os.getenv('COMPANY_NAME', 'AI Email Generator Co.')
        self.your_name = your_name or os.getenv('YOUR_NAME', 'John Doe')
        self.your_position = your_position or os.getenv('YOUR_POSITION', 'AI Solutions Specialist')
        self.your_contact = your_contact or os.getenv('YOUR_CONTACT', 'contact@aiemail.com')
        
        # Cache pour éviter de régénérer les emails
        self.cache_file = cache_file
        self.cache = self.load_cache()
        
        # Template par défaut
        self.default_template = """
Dear [FirstName],

I hope this email finds you well. My name is [YourName], [YourPosition] at [YourCompany], and I noticed that [Company] has been making significant strides in the [Industry] sector.

[CustomParagraph]

I'd love to schedule a brief call to discuss how our AI solutions could specifically help [Company] with [Challenge]. Would you be available for a 15-minute conversation next week?

Best regards,
[YourName]
[YourPosition]
[YourContact]
"""
        logger.info(f"Initialisation terminée: API key set: {bool(self.api_key)}, Endpoint set: {bool(self.api_endpoint)}")
        self.verify_api_configuration()

    def verify_api_configuration(self) -> bool:
        """
        Vérifie que la configuration de l'API est valide.
        
        Returns:
            bool: True si la configuration est valide, False sinon
        """
        valid = True
        
        # Vérifier la présence de l'API key
        if not self.api_key:
            logger.error("ERREUR: Clé API Azure OpenAI manquante. Vérifiez votre fichier .env")
            valid = False
        elif len(self.api_key) < 10:  # Vérification basique
            logger.warning("ATTENTION: La clé API Azure OpenAI semble invalide")
            valid = False
            
        # Vérifier l'endpoint
        if not self.api_endpoint:
            logger.error("ERREUR: Endpoint Azure OpenAI manquant. Vérifiez votre fichier .env")
            valid = False
        elif not (self.api_endpoint.startswith('https://') and ('.openai.azure.com' in self.api_endpoint or '.cognitiveservices.azure.com' in self.api_endpoint)):
            logger.warning(f"ATTENTION: L'endpoint Azure OpenAI semble invalide: {self.api_endpoint}")
            valid = False
            
        # Vérifier le deployment name
        if not self.deployment_name:
            logger.error("ERREUR: Nom de déploiement Azure OpenAI manquant. Vérifiez votre fichier .env")
            valid = False
            
        # Vérifier les variables d'expéditeur
        missing_vars = []
        if not os.getenv('COMPANY_NAME'): missing_vars.append('COMPANY_NAME')
        if not os.getenv('YOUR_NAME'): missing_vars.append('YOUR_NAME')
        if not os.getenv('YOUR_POSITION'): missing_vars.append('YOUR_POSITION')
        if not os.getenv('YOUR_CONTACT'): missing_vars.append('YOUR_CONTACT')
        
        if missing_vars:
            logger.warning(f"ATTENTION: Variables d'expéditeur manquantes: {', '.join(missing_vars)}. Les valeurs par défaut seront utilisées.")
            
        return valid

    def load_cache(self) -> Dict[str, Any]:
        """
        Charge le cache depuis le fichier
        
        Returns:
            Dict: Cache chargé depuis le fichier, ou dictionnaire vide si le fichier n'existe pas
        """
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                logger.info(f"Cache chargé: {len(cache)} entrées trouvées")
                return cache
            else:
                logger.info("Aucun fichier de cache trouvé, création d'un cache vide")
                return {}
        except Exception as e:
            logger.error(f"Erreur lors du chargement du cache: {str(e)}")
            return {}

    def save_cache(self):
        """Sauvegarde le cache dans le fichier"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            logger.info(f"Cache sauvegardé: {len(self.cache)} entrées")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du cache: {str(e)}")

    def read_contacts(self, csv_file):
        """
        Lit un fichier CSV et extrait les informations de contact.
        """
        logging.getLogger('email_generator').info(f"Lecture du fichier CSV: {csv_file}")
        contacts = []
        
        try:
            with open(csv_file, 'r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.DictReader(f)
                # Loguer les informations sur le CSV
                fieldnames = reader.fieldnames
                logging.getLogger('email_generator').info(f"Nombre de lignes: {sum(1 for _ in open(csv_file))-1}, Colonnes: {', '.join(fieldnames)}")
                
                # Créer un mappage pour normaliser les noms de colonnes
                column_mapping = {
                    'first_name': ['first_name', 'firstname', 'first name', 'given name', 'prénom'],
                    'last_name': ['last_name', 'lastname', 'last name', 'surname', 'nom'],
                    'email': ['email', 'e-mail', 'courriel', 'mail'],
                    'company': ['company', 'société', 'organization', 'organisation', 'company name', 'company name for emails'],
                    'position': ['position', 'title', 'function', 'job title', 'poste', 'role'],
                    'industry': ['industry', 'sector', 'domaine', 'secteur'],
                    'technologies': ['technologies', 'tech', 'stack', 'solutions', 'technology'],
                    'keywords': ['keywords', 'tags', 'mots clés', 'sujets'],
                    'linkedin_url': ['linkedin_url', 'linkedin', 'linkedin url', 'person linkedin url'],
                    'company_linkedin_url': ['company_linkedin_url', 'company_linkedin', 'company linkedin url', 'company linkedin'],
                    'twitter_url': ['twitter_url', 'twitter', 'twitter url'],
                    'website': ['website', 'site', 'web', 'company website', 'company site', 'url', 'site web'],
                    'description': ['description', 'seo description', 'about', 'à propos'],
                    'challenges': ['challenges', 'défis', 'problems', 'problèmes', 'needs', 'besoins']
                }
                
                # Créer un mappage inverse des colonnes actuelles
                actual_columns = {}
                for col in fieldnames:
                    normalized_col = col.lower().strip()
                    for target, possible_names in column_mapping.items():
                        if normalized_col in possible_names or normalized_col.replace(' ', '_') in possible_names:
                            actual_columns[target] = col
                            break
                
                # Vérifier les colonnes requises
                required_columns = ['first_name', 'last_name', 'email', 'company']
                missing_columns = [col for col in required_columns if col not in actual_columns]
                
                if missing_columns:
                    logging.getLogger('email_generator').warning(f"Colonnes manquantes dans le CSV: {', '.join(missing_columns)}")
                    raise ValueError(f"Colonnes requises manquantes dans le CSV: {', '.join(missing_columns)}")
                
                # Lire les données
                for row in reader:
                    contact_info = {}
                    for target, actual_col in actual_columns.items():
                        contact_info[target] = row.get(actual_col, '')
                    
                    # Extraire les défis s'ils existent
                    challenges = []
                    if 'challenges' in actual_columns:
                        challenges_text = contact_info.get('challenges', '')
                        if challenges_text:
                            challenges = [c.strip() for c in challenges_text.split(',')]
                    contact_info['challenges'] = challenges
                    
                    # Extraire les technologies s'ils existent
                    technologies = []
                    if 'technologies' in actual_columns:
                        technologies_text = contact_info.get('technologies', '')
                        if technologies_text:
                            technologies = [t.strip() for t in technologies_text.split(',')]
                    contact_info['technologies'] = technologies
                    
                    # Extraire les mots-clés s'ils existent
                    keywords = []
                    if 'keywords' in actual_columns:
                        keywords_text = contact_info.get('keywords', '')
                        if keywords_text:
                            keywords = [k.strip() for k in keywords_text.split(',')]
                    contact_info['keywords'] = keywords
                    
                    contacts.append(contact_info)
                
            return contacts
        except Exception as e:
            logging.getLogger('email_generator').error(f"Erreur lors de la lecture des contacts: {str(e)}")
            raise

    def extract_company_challenges(self, contact_info: Dict[str, Any]) -> List[str]:
        """
        Extrait ou déduit les défis potentiels de l'entreprise à partir des informations de contact
        
        Args:
            contact_info (Dict): Informations de contact
            
        Returns:
            List[str]: Liste des défis potentiels
        """
        challenges = []
        
        # Utiliser les défis explicites s'ils sont disponibles
        if 'challenges' in contact_info and contact_info['challenges']:
            return contact_info['challenges']
        
        # Déduire les défis à partir des technologies
        tech_challenge_map = {
            'legacy': 'modernisation des systèmes hérités',
            'mainframe': 'modernisation des systèmes hérités',
            'cobol': 'modernisation des systèmes hérités',
            'on-premise': 'migration vers le cloud',
            'on premise': 'migration vers le cloud',
            'excel': 'automatisation des processus',
            'manual': 'automatisation des processus',
            'data': 'analyse de données',
            'analytics': 'analyse de données',
            'ai': 'intelligence artificielle',
            'ml': 'machine learning',
            'security': 'cybersécurité',
            'secure': 'cybersécurité',
            'compliance': 'conformité réglementaire',
            'regulation': 'conformité réglementaire',
            'customer': 'expérience client',
            'crm': 'gestion de la relation client',
            'cost': 'réduction des coûts',
            'automation': 'automatisation des processus',
        }
        
        if 'technologies' in contact_info and contact_info['technologies']:
            for tech in contact_info['technologies']:
                for keyword, challenge in tech_challenge_map.items():
                    if keyword.lower() in tech.lower() and challenge not in challenges:
                        challenges.append(challenge)
        
        # Déduire les défis à partir des mots-clés
        if 'keywords' in contact_info and contact_info['keywords']:
            for keyword in contact_info['keywords']:
                for key, challenge in tech_challenge_map.items():
                    if key.lower() in keyword.lower() and challenge not in challenges:
                        challenges.append(challenge)
        
        # Si toujours pas de défis, ajouter des défis génériques
        if not challenges:
            industry = contact_info.get('industry', '').lower()
            position = contact_info.get('position', '').lower()
            
            if 'cto' in position or 'technology' in position or 'tech' in position:
                challenges.append('innovation technologique')
            elif 'cio' in position or 'information' in position:
                challenges.append('transformation digitale')
            elif 'ceo' in position or 'founder' in position or 'president' in position:
                challenges.append('croissance de l\'entreprise')
            elif 'cfo' in position or 'finance' in position:
                challenges.append('optimisation des coûts')
            elif 'marketing' in position:
                challenges.append('génération de leads')
            elif 'sales' in position or 'revenue' in position:
                challenges.append('augmentation des ventes')
            elif 'hr' in position or 'people' in position or 'talent' in position:
                challenges.append('gestion des talents')
            elif 'product' in position:
                challenges.append('innovation produit')
            elif 'operations' in position or 'coo' in position:
                challenges.append('efficacité opérationnelle')
            else:
                challenges.append('transformation digitale')
        
        return challenges

    def generate_email_content_with_template(self, contact_info: Dict[str, Any]) -> Dict[str, str]:
        """
        Génère le contenu d'un email à partir d'un template
        
        Args:
            contact_info (Dict): Informations de contact
            
        Returns:
            Dict: Contenu de l'email (subject, body)
        """
        # Extraire ou déduire les défis de l'entreprise
        challenges = self.extract_company_challenges(contact_info)
        selected_challenge = challenges[0] if challenges else "transformation digitale"
        
        # Mapper les défis français vers l'anglais
        challenge_map = {
            "transformation digitale": "digital transformation",
            "modernisation des systèmes hérités": "legacy system modernization",
            "migration vers le cloud": "cloud migration",
            "automatisation des processus": "process automation",
            "analyse de données": "data analytics",
            "intelligence artificielle": "artificial intelligence",
            "machine learning": "machine learning",
            "cybersécurité": "cybersecurity",
            "conformité réglementaire": "regulatory compliance",
            "expérience client": "customer experience",
            "gestion de la relation client": "customer relationship management",
            "réduction des coûts": "cost reduction",
            "croissance de l'entreprise": "business growth",
            "innovation technologique": "technological innovation",
            "optimisation des coûts": "cost optimization",
            "génération de leads": "lead generation",
            "augmentation des ventes": "sales growth",
            "gestion des talents": "talent management",
            "innovation produit": "product innovation",
            "efficacité opérationnelle": "operational efficiency"
        }
        
        english_challenge = challenge_map.get(selected_challenge, "digital transformation")
        
        # Créer un paragraphe personnalisé en anglais
        custom_paragraph = f"I understand that {contact_info['company']} might be facing challenges related to {english_challenge}. Our AI solutions have helped similar companies in your industry to address these challenges, resulting in significant efficiency improvements and cost savings."
        
        # Remplacer les placeholders dans le template
        body = self.default_template
        body = body.replace('[FirstName]', contact_info['first_name'])
        body = body.replace('[YourName]', self.your_name)
        body = body.replace('[YourCompany]', self.company_name)
        body = body.replace('[Company]', contact_info['company'])
        body = body.replace('[Industry]', contact_info.get('industry', 'technology'))
        body = body.replace('[CustomParagraph]', custom_paragraph)
        body = body.replace('[Challenge]', english_challenge)
        body = body.replace('[YourPosition]', self.your_position)
        body = body.replace('[YourContact]', self.your_contact)
        
        # Créer l'objet de l'email en anglais
        subject = f"AI Solutions for {english_challenge} at {contact_info['company']}"
        
        return {
            'subject': subject,
            'body': body
        }

    def generate_email_content_with_ai(self, contact_info: Dict[str, Any]) -> Dict[str, str]:
        """
        Génère le contenu d'un email en utilisant l'API d'OpenAI
        
        Args:
            contact_info (Dict): Informations de contact
            
        Returns:
            Dict: Contenu de l'email (subject, body)
        """
        # Calculer l'ID unique pour le cache
        contact_id = f"{contact_info['email']}_{contact_info['company']}"
        
        # Vérifier si l'email est déjà dans le cache
        if contact_id in self.cache:
            logger.info(f"Email trouvé dans le cache pour {contact_info['email']}")
            return self.cache[contact_id]['email_data']
        
        # Vérifier que l'API est correctement configurée
        if not self.verify_api_configuration():
            logger.error("Génération d'email avec IA impossible: API non configurée")
            # En cas d'erreur, utiliser le template par défaut
            return self.generate_email_content_with_template(contact_info)
        
        logger.info(f"Génération d'email avec IA pour {contact_info['email']}")
        
        # Extraire les challenges
        challenges = self.extract_company_challenges(contact_info)
        challenges_str = ", ".join(challenges) if challenges else "digital transformation"
        
        # Afficher les informations personnalisées pour le débogage
        logger.debug(f"Utilisation des informations d'expéditeur: nom={self.your_name}, poste={self.your_position}, société={self.company_name}, contact={self.your_contact}")
        
        # Construire le prompt pour l'API
        prompt = f"""
Write a personalized outreach email from {self.your_name} ({self.your_position}) at {self.company_name} to {contact_info['first_name']} {contact_info['last_name']} at {contact_info['company']}.

Contact information:
- Name: {contact_info['first_name']} {contact_info['last_name']}
- Company: {contact_info['company']}
- Position: {contact_info.get('position', 'Decision Maker')}
- Company challenges: {challenges_str}

The email should:
1. Have a concise subject line that mentions AI solutions and {contact_info['company']}
2. Be written in English, professional but conversational
3. Be brief and to the point (no more than 150 words)
4. Highlight how our AI solutions from {self.company_name} can help with their challenges
5. Suggest a brief 15-minute call
6. Include a signature with my name ({self.your_name}), position ({self.your_position}), and contact info: {self.your_contact}

Return the email in JSON format with 'subject' and 'body' keys.
"""
        
        try:
            # Utiliser la bibliothèque azure-ai-inference
            try:
                from azure.ai.inference import ChatCompletionsClient
                from azure.core.credentials import AzureKeyCredential
            except ImportError:
                logger.error("Bibliothèque azure-ai-inference non installée. Installation avec: pip install azure-ai-inference")
                # Installer automatiquement si manquant
                import subprocess
                subprocess.check_call(["pip", "install", "azure-ai-inference"])
                from azure.ai.inference import ChatCompletionsClient
                from azure.core.credentials import AzureKeyCredential
            
            # Initialiser le client Azure OpenAI avec les paramètres corrects
            client = ChatCompletionsClient(
                endpoint=self.api_endpoint,
                credential=AzureKeyCredential(self.api_key)
            )
            
            logger.debug(f"Appel API Azure AI Inference avec modèle: {self.deployment_name}")
            
            # Vérifier si la version de l'API est spécifiée, sinon utiliser une version par défaut
            api_version = self.azure_openai_api_version or "2023-12-01-preview"
            
            # Construction de l'URL complète pour éviter les erreurs 404
            # L'URL correcte devrait être de la forme: https://{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}
            endpoint = self.api_endpoint.rstrip('/')
            
            logger.debug(f"Utilisation de la version d'API: {api_version}")
            logger.debug(f"URL complète: {endpoint}/openai/deployments/{self.deployment_name}/chat/completions")
            
            # Appeler l'API OpenAI avec la nouvelle syntaxe
            try:
                # Utiliser directement le client OpenAI classique car il gère mieux le format d'URL d'Azure
                from openai import AzureOpenAI
                
                client = AzureOpenAI(
                    api_key=self.api_key,
                    api_version=api_version,
                    azure_endpoint=self.api_endpoint
                )
                
                response = client.chat.completions.create(
                    model=self.deployment_name,
                    messages=[
                        {"role": "system", "content": "You are an expert email copywriter specializing in personalized outreach."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=800,
                    top_p=0.95,
                    frequency_penalty=0,
                    presence_penalty=0
                )
                
                # Adapter la réponse au format attendu
                response_text = response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Erreur lors de l'appel à l'API avec OpenAI SDK: {str(e)}")
                
                # Essayer avec la bibliothèque azure-ai-inference comme fallback
                try:
                    response = client.complete(
                        messages=[
                            {"role": "system", "content": "You are an expert email copywriter specializing in personalized outreach."},
                            {"role": "user", "content": prompt}
                        ],
                        model=self.deployment_name,
                        temperature=0.7,
                        max_tokens=800,
                        top_p=0.95,
                        frequency_penalty=0,
                        presence_penalty=0
                    )
                    
                    # Extraire la réponse
                    response_text = response.choices[0].message.content.strip()
                except Exception as fallback_error:
                    logger.error(f"Erreur avec la méthode alternative: {str(fallback_error)}")
                    raise
            
            # Tenter de parser la réponse JSON
            try:
                # Trouver les accolades JSON dans la réponse
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    email_data = json.loads(json_str)
                    
                    # Vérifier que les clés nécessaires sont présentes
                    if 'subject' not in email_data or 'body' not in email_data:
                        raise ValueError("Les clés 'subject' et 'body' sont nécessaires")
                    
                    # Ajouter au cache
                    self.cache[contact_id] = {
                        'email_data': email_data,
                        'timestamp': datetime.now().isoformat()
                    }
                    self.save_cache()
                    
                    logger.info(f"Email généré avec succès pour {contact_info['email']}")
                    return email_data
                else:
                    raise ValueError("Format JSON non trouvé dans la réponse")
            except Exception as e:
                logger.error(f"Erreur lors du parsing de la réponse JSON: {str(e)}")
                logger.debug(f"Réponse brute: {response_text}")
                
                # Essayer de construire manuellement un JSON à partir de la réponse
                lines = response_text.split('\n')
                subject = ""
                body = ""
                
                for i, line in enumerate(lines):
                    if 'subject' in line.lower() and ':' in line and not subject:
                        subject = line.split(':', 1)[1].strip().strip('"').strip()
                    elif 'body' in line.lower() and ':' in line and not body:
                        # Le corps peut être sur plusieurs lignes
                        body_start = i
                        # Trouver la fin du corps (jusqu'à la prochaine clé ou la fin du texte)
                        body_end = body_start + 1
                        while body_end < len(lines) and not any(key in lines[body_end].lower() for key in ['"subject":', 'subject:', '"to":', 'to:']):
                            body_end += 1
                        
                        body = '\n'.join(lines[body_start:body_end])
                        body = body.split(':', 1)[1].strip().strip('"').strip()
                
                if not subject or not body:
                    raise ValueError("Impossible d'extraire le sujet ou le corps de l'email")
                
                email_data = {
                    'subject': subject,
                    'body': body
                }
                
                # Ajouter au cache
                self.cache[contact_id] = {
                    'email_data': email_data,
                    'timestamp': datetime.now().isoformat()
                }
                self.save_cache()
                
                logger.info(f"Email généré avec succès (extraction manuelle) pour {contact_info['email']}")
                return email_data
                
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'email avec l'API: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Détails de la réponse: {e.response}")
            
            # En cas d'erreur, utiliser le template par défaut
            return self.generate_email_content_with_template(contact_info)

    def save_email_to_file(self, email_data: Dict[str, str], contact_info: Dict[str, Any], output_dir: str = "emails"):
        """
        Sauvegarde un email dans un fichier
        
        Args:
            email_data (Dict): Données de l'email (subject, body)
            contact_info (Dict): Informations de contact
            output_dir (str): Dossier de sortie
        """
        try:
            # Créer le dossier de sortie s'il n'existe pas
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                logger.info(f"Dossier créé: {output_dir}")
            
            # Créer un nom de fichier unique
            timestamp = int(time.time())
            filename = f"{output_dir}/{contact_info['first_name']}_{contact_info['last_name']}_{timestamp}.txt"
            
            # Écrire l'email dans le fichier
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"To: {contact_info['email']}\n")
                f.write(f"Subject: {email_data['subject']}\n\n")
                f.write(email_data['body'])
            
            logger.info(f"Email sauvegardé: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de l'email: {str(e)}")
            return None

    def save_emails_to_consolidated_file(self, results: List[Dict[str, Any]], output_file: str = "all_emails.txt"):
        """
        Sauvegarde tous les emails dans un fichier consolidé
        
        Args:
            results (List[Dict]): Liste des résultats
            output_file (str): Nom du fichier de sortie
        """
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                for i, result in enumerate(results):
                    contact_info = result['contact_info']
                    email_data = result['email_data']
                    
                    f.write(f"=== Email {i+1} ===\n")
                    f.write(f"To: {contact_info['email']}\n")
                    f.write(f"Subject: {email_data['subject']}\n\n")
                    f.write(email_data['body'])
                    f.write("\n\n" + "="*50 + "\n\n")
            
            logger.info(f"Emails consolidés sauvegardés: {output_file}")
            return output_file
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des emails consolidés: {str(e)}")
            return None

    def verify_contact_in_cache(self, contact_email: str, company: str) -> bool:
        """
        Vérifie si un contact est déjà dans le cache
        
        Args:
            contact_email (str): Email du contact
            company (str): Entreprise du contact
            
        Returns:
            bool: True si le contact est dans le cache, False sinon
        """
        # Vérifier dans le cache local
        contact_id = f"{contact_email}_{company}"
        if contact_id in self.cache:
            logger.info(f"Contact trouvé dans le cache local: {contact_email}")
            return True
            
        # Vérifier dans le cache partagé des amis
        try:
            # Cette fonction serait remplacée par une vraie vérification 
            # via une base de données ou une API dans une application de production
            friends_cache_file = "friends_shared_cache.json"
            if os.path.exists(friends_cache_file):
                with open(friends_cache_file, 'r', encoding='utf-8') as f:
                    friends_cache = json.load(f)
                    if contact_id in friends_cache:
                        logger.info(f"Contact trouvé dans le cache partagé: {contact_email}")
                        # Ajouter au cache local pour les futures références
                        self.cache[contact_id] = friends_cache[contact_id]
                        self.save_cache()
                        return True
        except Exception as e:
            logger.error(f"Erreur lors de la vérification du cache partagé: {str(e)}")
            # En cas d'erreur, on considère que le contact n'est pas dans le cache
            pass
            
        return False
        
    def process_contact(self, contact_info: Dict[str, str], use_ai: bool = True, template_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Traite un contact individuel et génère un email personnalisé
        
        Args:
            contact_info (Dict): Informations de contact
            use_ai (bool): Utiliser l'IA pour la génération
            template_id (str, optional): ID du template à utiliser
            
        Returns:
            Dict: Informations de contact et email généré
        """
        # Vérifier si le contact a déjà été traité
        if self.verify_contact_in_cache(contact_info['email'], contact_info['company']):
            email_data = self.cache[f"{contact_info['email']}_{contact_info['company']}"]['email_data']
            return {
                'contact_info': contact_info,
                'email_data': email_data,
                'from_cache': True
            }
            
        # Générer un email pour ce contact
        if use_ai and self.verify_api_configuration():
            email_data = self.generate_email_content_with_ai(contact_info)
        else:
            email_data = self.generate_email_content_with_template(contact_info)
            
        # Enregistrer dans le cache
        self.save_to_cache(contact_info['email'], contact_info['company'], email_data)
        
        return {
            'contact_info': contact_info,
            'email_data': email_data,
            'from_cache': False
        }
        
    def save_to_cache(self, email: str, company: str, email_data: Dict[str, str]) -> None:
        """
        Sauvegarde un email généré dans le cache
        
        Args:
            email (str): Email du contact
            company (str): Entreprise du contact
            email_data (Dict): Données de l'email généré
        """
        contact_id = f"{email}_{company}"
        self.cache[contact_id] = {
            'email_data': email_data,
            'timestamp': datetime.now().isoformat()
        }
        self.save_cache()
        
        # Synchroniser avec le cache partagé des amis actifs
        self.sync_with_friends_cache(email, company, email_data)
        
    def sync_with_friends_cache(self, email: str, company: str, email_data: Dict[str, str]) -> None:
        """
        Synchronise une entrée de cache avec le cache partagé des amis
        
        Args:
            email (str): Email du contact
            company (str): Entreprise du contact
            email_data (Dict): Données de l'email généré
        """
        try:
            # Cette fonction serait remplacée par une vraie synchronisation 
            # via une base de données ou une API dans une application de production
            friends_data_file = "friends_data.json"
            if not os.path.exists(friends_data_file):
                return
                
            with open(friends_data_file, 'r', encoding='utf-8') as f:
                friends_data = json.load(f)
                
            active_friends = [friend for friend in friends_data.get('friends', []) 
                             if friend.get('sharing_enabled', False)]
                             
            if not active_friends:
                return
                
            # Préparer l'entrée à synchroniser
            entry = {
                'email': email,
                'company': company,
                'timestamp': datetime.now().isoformat(),
                'email_data': email_data
            }
            
            # Synchroniser avec le cache partagé
            friends_cache_file = "friends_shared_cache.json"
            shared_cache = {}
            
            if os.path.exists(friends_cache_file):
                with open(friends_cache_file, 'r', encoding='utf-8') as f:
                    shared_cache = json.load(f)
                    
            contact_id = f"{email}_{company}"
            shared_cache[contact_id] = entry
            
            with open(friends_cache_file, 'w', encoding='utf-8') as f:
                json.dump(shared_cache, f, default=str)
                
            logger.info(f"Email synchronisé avec le cache partagé des amis: {email}")
        except Exception as e:
            logger.error(f"Erreur lors de la synchronisation avec le cache partagé: {str(e)}")
            # En cas d'erreur, on continue sans synchroniser

    def process_contacts(self, csv_file: str, use_ai: bool = True, output_dir: str = "emails") -> List[Dict[str, Any]]:
        """
        Traite les contacts depuis un fichier CSV et génère des emails
        
        Args:
            csv_file (str): Chemin vers le fichier CSV
            use_ai (bool): Utiliser l'IA ou le template
            output_dir (str): Dossier de sortie
            
        Returns:
            List[Dict]: Liste des résultats (contact_info, email_data, output_file)
        """
        results = []
        
        try:
            logger.info(f"Début du traitement des contacts: {csv_file}, utilisation de l'IA: {use_ai}")
            
            # Lire les contacts
            contacts = self.read_contacts(csv_file)
            
            for contact in contacts:
                try:
                    # Générer le contenu de l'email
                    if use_ai:
                        email_data = self.generate_email_content_with_ai(contact)
                    else:
                        email_data = self.generate_email_content_with_template(contact)
                    
                    # Sauvegarder l'email dans un fichier
                    output_file = self.save_email_to_file(email_data, contact, output_dir)
                    
                    # Ajouter aux résultats
                    results.append({
                        'contact_info': contact,
                        'email_data': email_data,
                        'output_file': output_file
                    })
                except Exception as e:
                    logger.error(f"Erreur lors du traitement du contact {contact.get('email', 'inconnu')}: {str(e)}")
            
            # Sauvegarder tous les emails dans un fichier consolidé
            if results:
                self.save_emails_to_consolidated_file(results)
            
            logger.info(f"Traitement terminé: {len(results)}/{len(contacts)} emails générés")
            return results
        except Exception as e:
            logger.error(f"Erreur lors du traitement des contacts: {str(e)}")
            return results 