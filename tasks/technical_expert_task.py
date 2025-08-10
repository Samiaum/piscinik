# tasks/technical_expert_task.py - Avec RAG intégré
from typing import Annotated
from pydantic import Field
from livekit.agents.llm import function_tool
from livekit.agents import Agent, RunContext
from .global_functions import (
    get_date_today,
    transfer_to_receptionist,
    transfer_to_scheduler,
    transfer_to_messenger,
    update_information,
    get_user_info,
)

# Import du système RAG (import absolu)
from rag_system import get_rag_system

class TechnicalExpert(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""Vous êtes l'expert technique de Piscinik. Pour TOUTE question sur les piscines, 
            utilisez IMMÉDIATEMENT la fonction technical_advice_rag pour donner une réponse basée sur votre expertise.
            
            Exemples de questions qui nécessitent technical_advice_rag :
            - Eau verte, trouble, ou problèmes d'algues
            - Questions sur le pH, chlore, ou chimie de l'eau  
            - Problèmes d'équipements (pompe, filtre, chauffage)
            - Conseils d'entretien ou de maintenance
            - Toute question technique sur les piscines
            
            Utilisez TOUJOURS technical_advice_rag avant de répondre à une question technique.""",
            tools=[
                update_information,
                get_user_info,
                transfer_to_receptionist,
                transfer_to_scheduler,
                transfer_to_messenger,
                get_date_today,
            ],
        )

    async def on_enter(self) -> None:
        # L'expert technique reste silencieux jusqu'à ce que le client pose
        # sa question afin d'éviter toute génération non sollicitée.
        pass

    @function_tool()
    async def technical_advice_rag(
        self,
        question: Annotated[str, Field(description="N'IMPORTE QUELLE question technique du client sur sa piscine - utilisez cette fonction pour TOUTE question")],
        context: RunContext,
    ) -> str:
        """
        FONCTION PRINCIPALE : Fournit des conseils techniques pour TOUTE question sur les piscines.
        Utilisez cette fonction pour TOUS les problèmes : eau verte, pH, équipements, entretien, etc.
        """
        try:
            # Obtenir l'instance RAG
            rag = await get_rag_system()
            
            # Enrichir la question avec le contexte client
            pool_info = ""
            if context.userdata["userinfo"].pool_type:
                pool_info += f" Type de piscine: {context.userdata['userinfo'].pool_type}."
            if context.userdata["userinfo"].pool_size:
                pool_info += f" Taille: {context.userdata['userinfo'].pool_size}."
            
            enriched_question = f"{question}{pool_info}"
            
            # Obtenir la réponse RAG
            answer = await rag.get_answer(enriched_question)
            
            # LOG CRUCIAL pour debug
            print(f"🎯 RÉPONSE RAG REÇUE: {answer}")
            
            # Vérifier que la réponse n'est pas vide
            if not answer or answer.strip() == "":
                return "Je rencontre un problème technique avec ma base de connaissances. Laissez-moi vous aider autrement."
            
            return answer
            
        except Exception as e:
            print(f"❌ ERREUR technical_advice_rag: {e}")
            return f"Je rencontre un problème technique pour accéder à ma base de connaissances. Pouvez-vous reformuler votre question ? Si le problème est urgent, je peux vous transférer pour planifier une intervention."

    @function_tool()
    async def water_chemistry_advice(
        self,
        issue: Annotated[str, Field(description="Le problème chimique de l'eau décrit par le client")],
        context: RunContext,
    ) -> str:
        """
        Fournit des conseils sur l'équilibrage chimique de l'eau de piscine.
        """
        # Utiliser le RAG pour les conseils chimiques
        return await self.technical_advice_rag(f"Problème chimique eau piscine: {issue}", context)

    @function_tool()
    async def equipment_troubleshooting(
        self,
        equipment: Annotated[str, Field(description="L'équipement concerné par le problème")],
        problem: Annotated[str, Field(description="Description du problème rencontré")],
        context: RunContext,
    ) -> str:
        """
        Aide au diagnostic et dépannage des équipements de piscine.
        """
        # Utiliser le RAG pour le dépannage équipement
        return await self.technical_advice_rag(f"Problème équipement {equipment}: {problem}", context)

    @function_tool()
    async def maintenance_schedule_advice(
        self,
        context: RunContext,
    ) -> str:
        """
        Fournit un planning d'entretien personnalisé selon le type de piscine.
        """
        pool_type = context.userdata["userinfo"].pool_type or "standard"
        pool_size = context.userdata["userinfo"].pool_size or "moyenne"
        
        # Utiliser le RAG pour les conseils d'entretien
        return await self.technical_advice_rag(f"Planning entretien piscine {pool_type} {pool_size}", context)

    @function_tool()
    async def seasonal_advice(
        self,
        season: Annotated[str, Field(description="La saison concernée : printemps, été, automne, hiver")],
        context: RunContext,
    ) -> str:
        """
        Conseils d'entretien saisonnier pour la piscine.
        """
        # Utiliser le RAG pour les conseils saisonniers
        return await self.technical_advice_rag(f"Entretien piscine saison {season}", context)

    @function_tool()
    async def emergency_advice(
        self,
        emergency: Annotated[str, Field(description="Description de l'urgence ou problème grave")],
        context: RunContext,
    ) -> str:
        """
        Conseils d'urgence pour problèmes graves de piscine.
        """
        # Pour les urgences, on combine RAG + conseils sécurité
        rag_advice = await self.technical_advice_rag(f"Urgence piscine: {emergency}", context)
        
        safety_advice = """
        
        SÉCURITÉ IMMÉDIATE :
        1. Interdire la baignade si risque
        2. Couper l'alimentation électrique si nécessaire
        3. Photographier le problème
        
        Souhaitez-vous planifier une intervention d'urgence ?"""
        
        return rag_advice + safety_advice