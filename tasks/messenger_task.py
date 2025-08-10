# tasks/messenger_task.py
import os
from typing import Annotated
from pydantic import Field
from supabase import AsyncClient, create_async_client
from livekit.agents.llm import function_tool
from livekit.agents.voice import Agent, RunContext
from livekit.plugins import openai  # ✅ Changé : cartesia → openai
from .global_functions import (
    get_date_today,
    transfer_to_receptionist,
    transfer_to_scheduler,
    transfer_to_technical_expert,
    update_information,
)

class SupabaseClient:
    def __init__(self, supabase: AsyncClient) -> None:
        self._supabase = supabase

    @classmethod
    async def initiate_supabase(supabase):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_API_KEY")
        supabase_client: AsyncClient = await create_async_client(url, key)
        return supabase(supabase_client)

    async def insert_msg(self, name: str, message: str, phone: str, pool_info: str = None) -> list:
        data = await (
            self._supabase.table("messages")
            .insert({
                "name": name, 
                "message": message, 
                "phone_number": phone,
                "pool_info": pool_info,
                "service_type": "piscinik"
            })
            .execute()
        )
        return data

class Messenger(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""Vous êtes Shimmer, assistant chargé de prendre les messages pour Piscinik.
            Collectez le nom, numéro de téléphone et le message du client. Si possible, demandez aussi
            des informations sur leur piscine (type, taille) pour que notre équipe puisse mieux les aider.
            Confirmez les détails, surtout le numéro de téléphone. Soyez bref et professionnel.""",
            tts=openai.TTS(  # ✅ Changé : cartesia.TTS → openai.TTS
                voice="fable",  # ✅ Changé : voix élégante et raffinée pour service client
                model="gpt-4o-mini-tts",  # ✅ Ajouté : modèle OpenAI TTS
                instructions="Parlez en français avec un accent naturel et professionnel. TOUJOURS vouvoyer le client avec 'vous'. Ton courtois et aimable pour la prise de messages."  # ✅ Ajouté : instructions français
            ),
            tools=[
                update_information,
                transfer_to_receptionist,
                transfer_to_scheduler,
                transfer_to_technical_expert,
                get_date_today,
            ],
        )

    async def on_enter(self) -> None:
        self._supabase = await SupabaseClient.initiate_supabase()
        await self.session.generate_reply(
            instructions=f"""Présentez-vous et demandez leur numéro de téléphone
            s'il n'est pas déjà fourni. Ensuite, demandez quel message ils souhaitent laisser
            pour Piscinik concernant leur piscine. Informations déjà collectées: 
            {self.session.userdata["userinfo"].json()}"""
        )

    @function_tool()
    async def record_message(
        self,
        phone_number: Annotated[str, Field(description="Le numéro de téléphone du client")],
        message: Annotated[str, Field(description="Le message que le client souhaite laisser pour Piscinik")],
        context: RunContext,
    ) -> str:
        """Enregistre le message du client pour Piscinik ainsi que son numéro de téléphone."""
        context.userdata["userinfo"].phone = phone_number
        context.userdata["userinfo"].message = message
        
        # Informations piscine pour le message
        pool_info = ""
        if context.userdata["userinfo"].pool_type:
            pool_info += f"Type: {context.userdata['userinfo'].pool_type}"
        if context.userdata["userinfo"].pool_size:
            pool_info += f" - Taille: {context.userdata['userinfo'].pool_size}"
        
        try:
            data = await self._supabase.insert_msg(
                name=context.userdata["userinfo"].name,
                message=message,
                phone=phone_number,
                pool_info=pool_info if pool_info else None,
            )
            if data:
                return "Parfait ! Votre message a été enregistré. Un technicien Piscinik vous rappellera rapidement."
        except Exception as e:
            raise Exception(f"Erreur lors de l'envoi des données à Supabase: {e}") from None