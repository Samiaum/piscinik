# tasks/receptionist_task.py - VERSION STRICTE
from typing import Annotated
from datetime import datetime
from pydantic import Field
from livekit.agents.llm import function_tool
from livekit.agents import Agent, RunContext
from .global_functions import (
    get_date_today, 
    get_user_info, 
    update_information,
    transfer_to_technical_expert,
    get_recent_actions,
    check_recent_appointment,
    log_action
)

class Receptionist(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""Vous êtes Julie, réceptionniste chez Piscinik, spécialiste de l'entretien 
            et de la maintenance de piscines. 
            
            RÈGLES STRICTES - TRANSFERT IMMÉDIAT :
            1. Votre SEUL rôle : Identifier le nom + le type de demande
            2. ⚠️ TOUJOURS vérifier get_user_info("name") AVANT de demander le nom
            3. DÈS QUE vous avez ces 2 infos → TRANSFERT IMMÉDIAT 
            4. NE TRAITEZ JAMAIS vous-même les demandes de planification
            5. NE DONNEZ JAMAIS de conseils techniques
            6. NE PRENEZ JAMAIS de messages détaillés
            
            PROCESSUS STRICT :
            - Accueil chaleureux
            - VÉRIFIER get_user_info("name") en premier
            - Si nom connu → identifier le besoin et transférer IMMÉDIATEMENT
            - Si nom manquant → demander nom + besoin ensemble
            - TRANSFÉRER IMMÉDIATEMENT avec request_appointment(), technical_question(), ou leave_message()
            
            MESSAGES DE TRANSFERT OBLIGATOIRES :
            - Pour rendez-vous : "Parfait [nom] ! Je vous transfère vers notre planificateur, une seconde..."
            - Pour technique : "Un instant [nom], notre expert technique va vous aider..."
            - Pour message : "Je vous transfère vers notre service de messagerie, [nom]."
            
            INTERDICTIONS ABSOLUES :
            - Ne JAMAIS redemander un nom déjà dans get_user_info("name")
            - Ne JAMAIS dire "votre rendez-vous est en cours"
            - Ne JAMAIS dire "est-ce que je peux vous aider avec autre chose" après un transfert
            - Ne JAMAIS demander les détails (service, date, heure, problème technique)
            - Ne JAMAIS traiter la demande vous-même
            
            EXEMPLES DE BON COMPORTEMENT :
            ✅ Client connu demande technique : "Un instant Samuel, notre expert technique va vous aider..."
            ✅ Nouveau client : "Puis-je avoir votre nom et savoir comment vous orienter ?"
            ❌ Mauvais : "Pourriez-vous me rappeler votre nom..." (si déjà connu)
            
            DÈS IDENTIFICATION → TRANSFERT IMMÉDIAT !""",
            tools=[
                update_information, 
                get_user_info, 
                get_date_today, 
                transfer_to_technical_expert,
                get_recent_actions,
                check_recent_appointment,
                log_action
            ],
        )

    async def on_enter(self) -> None:
        # Récupérer les informations client
        userinfo = self.session.userdata["userinfo"]
        client_name = userinfo.name if userinfo.name else ""
        
        print(f"DEBUG Receptionist: Nom client: {client_name}")
        
        # Message d'accueil simple et direct
        if client_name:
            greeting = f"Re-bonjour {client_name} ! Comment puis-je vous orienter aujourd'hui ? Souhaitez-vous planifier un rendez-vous, poser une question technique, ou laisser un message ?"
        else:
            greeting = "Bonjour et bienvenue chez Piscinik ! Je suis Julie, votre réceptionniste. Puis-je avoir votre nom et savoir comment vous orienter ? (rendez-vous, question technique, ou message)"
        
        # Enregistrer l'interaction d'accueil
        session_history = self.session.userdata["session_history"]
        action_entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": "receptionist",
            "action": "customer_welcomed",
            "details": f"Accueil {client_name if client_name else 'nouveau client'}"
        }
        session_history.actions.append(action_entry)
        # Nova Sonic's realtime API does not allow generating speech before any
        # user audio has been received. Calling generate_reply here would
        # trigger an "unprompted generation" error at startup. Instead, the
        # receptionist waits for the caller to speak first and will craft a
        # greeting in response to the first user message.

    @function_tool()
    async def greet_with_context(
        self,
        context: RunContext,
    ) -> str:
        """
        Salue le client en tenant compte de l'historique récent de la session.
        """
        userinfo = context.userdata["userinfo"]
        client_name = userinfo.name if userinfo.name else "cher client"
        
        # Vérifier l'historique maintenant qu'on a le context
        recent_appointment = await check_recent_appointment(context)
        
        if recent_appointment != "None":
            if "appointment_scheduled" in recent_appointment:
                return f"Parfait {client_name} ! Je vois que votre rendez-vous vient d'être confirmé avec succès. Autre chose ?"
            elif "appointment_cancelled" in recent_appointment:
                return f"Votre annulation a bien été prise en compte {client_name}. Souhaitez-vous planifier un nouveau rendez-vous ?"
            elif "appointment_failed" in recent_appointment or "appointment_error" in recent_appointment:
                return f"Je vois que vous avez eu un petit souci lors de la planification {client_name}. Voulez-vous réessayer ?"
        
        return f"Comment puis-je vous orienter aujourd'hui {client_name} ? Rendez-vous, question technique, ou message ?"

    @function_tool()
    async def opening_hours(self) -> str:
        """Répond aux questions sur les horaires d'ouverture de Piscinik."""
        return """Piscinik est ouvert du lundi au samedi de 8h à 12h et de 14h à 18h. 
        Nous sommes fermés le dimanche."""

    @function_tool()
    async def location_inquiry(self) -> str:
        """Répond aux questions sur l'emplacement de Piscinik et les déplacements."""
        return """Piscinik est situé au 123 Avenue des Piscines. Nous nous déplaçons 
        dans toute la région pour l'entretien et les réparations de piscines. 
        Zone d'intervention : 50km autour de notre siège."""

    @function_tool()
    async def services_inquiry(self) -> str:
        """Répond aux questions sur les services proposés par Piscinik."""
        return """Piscinik propose :
        - Diagnostic complet de piscine
        - Entretien régulier (nettoyage, équilibrage chimique)
        - Réparations (filtration, étanchéité, équipements)
        - Installation d'équipements (pompes, filtres, chauffage, éclairage)
        - Hivernage et remise en service
        - Conseil technique personnalisé"""

    @function_tool()
    async def request_appointment(
        self,
        name: Annotated[str, Field(description="Le nom du client")],
        action: Annotated[
            str,
            Field(
                description="""L'action demandée :
                'planifier', 'replanifier', ou 'annuler'"""
            ),
        ],
        context: RunContext,
    ) -> tuple[Agent, str]:
        """
        TRANSFERT IMMÉDIAT vers le planificateur pour gérer les rendez-vous.
        La réceptionniste ne traite JAMAIS elle-même les demandes de planification.
        """
        if not context.userdata["userinfo"].name:
            context.userdata["userinfo"].name = name
        
        # Enregistrer la demande de rendez-vous
        await log_action(
            "receptionist", 
            f"appointment_request_{action}", 
            f"Demande de {action} par {name}", 
            context
        )
        
        # Messages de transfert STRICTES - Aucune ambiguïté
        transfer_messages = {
            "planifier": f"Parfait {name} ! Je vous transfère vers notre planificateur, une seconde...",
            "replanifier": f"D'accord {name}, je vous transfère pour modifier votre rendez-vous.",
            "annuler": f"Je vous transfère vers notre planificateur pour l'annulation, {name}."
        }
        
        # TRANSFERT IMMÉDIAT - Retourner le tuple pour déclencher le changement d'agent
        return context.userdata["agents"].scheduler(
            service=action
        ), transfer_messages.get(action, f"Je vous transfère vers notre planificateur, {name}.")

    @function_tool()
    async def leave_message(
        self, 
        name: Annotated[str, Field(description="Le nom du client")], 
        context: RunContext
    ) -> tuple[Agent, str]:
        """
        TRANSFERT IMMÉDIAT vers le service de messagerie.
        """
        if not context.userdata["userinfo"].name:
            context.userdata["userinfo"].name = name
            
        # Enregistrer la demande de message
        await log_action(
            "receptionist", 
            "message_request", 
            f"Demande de message par {name}", 
            context
        )
        
        # TRANSFERT IMMÉDIAT
        return context.userdata["agents"].messenger, f"Je vous transfère vers notre service de messagerie, {name}."

    @function_tool()
    async def technical_question(
        self,
        name: Annotated[str, Field(description="Le nom du client")],
        context: RunContext,
    ) -> tuple[Agent, str]:
        """
        TRANSFERT IMMÉDIAT vers l'expert technique.
        """
        # 🎯 CORRECTION : Vérifier si le nom existe déjà
        userinfo = context.userdata["userinfo"]
        if not userinfo.name:
            userinfo.name = name
        
        # Utiliser le nom existant
        client_name = userinfo.name
            
        # Enregistrer la demande technique
        await log_action(
            "receptionist", 
            "technical_request", 
            f"Question technique de {client_name}", 
            context
        )
        
        # TRANSFERT IMMÉDIAT
        return context.userdata["agents"].technical_expert, f"Un instant {client_name}, notre expert technique va vous aider..."