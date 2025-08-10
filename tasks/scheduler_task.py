# tasks/scheduler_task.py - Version avec mémoire de session - CORRIGÉE
import os
from enum import Enum
from typing import Annotated

import aiohttp
from pydantic import Field

from livekit.agents.llm import function_tool
from livekit.agents import Agent, RunContext

from .global_functions import (
    get_date_today,
    get_current_datetime_info,
    convert_french_time_to_iso,
    get_user_info,
    transfer_to_messenger,
    transfer_to_receptionist,
    transfer_to_technical_expert,
    update_information,
    log_action,
    get_recent_actions,
    check_recent_appointment,
)


class APIRequests(Enum):
    GET_APPTS = "get_appts"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"
    SCHEDULE = "schedule"
    GET_AVAILABILITY = "get_availability"


class Scheduler(Agent):
    def __init__(self, *, service: str) -> None:
        super().__init__(
            instructions="""Vous êtes Echo, planificateur de rendez-vous pour Piscinik. Toujours vouvoyer.
                            
                            COORDINATION IMPORTANTE :
                            1. NE redemandez JAMAIS des informations déjà collectées par la réceptionniste
                            2. Utilisez get_user_info() pour vérifier les informations disponibles
                            3. Si le nom/email/service sont déjà connus, passez directement à la planification
                            4. ENREGISTREZ chaque action importante avec log_action()
                            
                            GESTION DES DATES :
                            1. Utilisez convert_french_time_to_iso() pour convertir les demandes clients
                            2. Demandez à QUELLE DATE et QUELLE HEURE ils souhaitent leur rendez-vous
                            3. Ne proposez jamais de dates vous-même - laissez le client choisir
                            4. Confirmez toujours les détails avec le client
                            
                            PROCESSUS OPTIMISÉ :
                            - Vérifiez d'abord les infos existantes
                            - Demandez seulement ce qui manque pour le RDV
                            - Focalisez sur les préférences de date/heure du client
                            - Enregistrez les succès et échecs
                            
                            Services disponibles :
                            - diagnostic-piscine : Diagnostic complet
                            - entretien-piscine : Entretien régulier
                            - reparation-piscine : Réparation
                            - installation-equipement : Installation d'équipement""",
            tools=[
                update_information,
                get_user_info,
                get_current_datetime_info,
                convert_french_time_to_iso,
                transfer_to_receptionist,
                transfer_to_messenger,
                transfer_to_technical_expert,
                get_date_today,
                log_action,
                get_recent_actions,
                check_recent_appointment,
            ],
        )
        self._service_requested = service

    async def on_enter(self) -> None:
        self._event_ids = self.session.userdata["event_ids"]
        
        # Récupérer les informations déjà collectées
        userinfo = self.session.userdata["userinfo"]
        client_name = userinfo.name if userinfo.name else ""
        
        print(f"DEBUG: Event IDs disponibles: {self._event_ids}")
        print(f"DEBUG: Informations client disponibles - Nom: {userinfo.name}, Email: {userinfo.email}, Service: {self._service_requested}")
        
        # 🎯 CORRECTION 1 : Vérifier ce qui manque vraiment
        missing_info = []
        if not userinfo.name:
            missing_info.append("votre nom")
        if not userinfo.email:
            missing_info.append("votre email")
        
        # 🎯 CORRECTION 2 : Message adaptatif sans redemander ce qu'on a
        if userinfo.name and userinfo.email:
            # On a tout - aller directement à la planification
            service_label = self._service_requested.replace('-', ' ') if self._service_requested != 'planifier' else 'votre service piscine'
            await self.session.generate_reply(
                instructions=f"""Parfait {client_name} ! 
                
                Pour votre {service_label}, quand souhaitez-vous votre rendez-vous ?
                Quelle date et quelle heure vous conviennent le mieux ?
                
                (Exemples : "demain matin", "mardi 14h", "mercredi après-midi")"""
            )
        elif userinfo.name and not userinfo.email:
            # On a le nom, manque juste l'email
            await self.session.generate_reply(
                instructions=f"""Parfait {client_name} ! 
                
                Pour finaliser votre rendez-vous, j'ai juste besoin de votre adresse email."""
            )
        elif missing_info:
            # 🎯 CORRECTION 3 : Demander seulement ce qui manque
            missing_text = " et ".join(missing_info)
            await self.session.generate_reply(
                instructions=f"""Pour organiser votre rendez-vous, j'ai besoin de {missing_text}.
                
                Pouvez-vous me donner ces informations ?"""
            )

    async def send_request(
        self,
        *,
        request: APIRequests,
        uid: str = "",
        time: str = "",
        slug: str = "",
        context: RunContext,
    ) -> dict:
        headers = {
            "cal-api-version": "2024-08-13",
            "Authorization": "Bearer " + os.getenv("CAL_API_KEY"),
        }
        async with aiohttp.ClientSession() as session:
            params = {}
            
            if request.value == "get_appts":
                payload = {
                    "attendeeEmail": context.userdata["userinfo"].email,
                    "attendeeName": context.userdata["userinfo"].name,
                    "status": "upcoming",
                }
                params = {
                    "url": "https://api.cal.com/v2/bookings",
                    "params": payload,
                    "headers": headers,
                }

            elif request.value == "get_availability":
                params = {
                    "url": f"https://api.cal.com/v2/slots/available",
                    "params": {
                        "eventTypeId": self._event_ids[slug],
                        "startTime": time,
                        "endTime": time,
                    },
                    "headers": headers,
                }

            elif request.value == "cancel":
                payload = {"cancellationReason": "Annulation demandée par le client"}
                params = {
                    "url": f"https://api.cal.com/v2/bookings/{uid}/cancel",
                    "json": payload,
                    "headers": headers,
                }

            elif request.value == "schedule":
                attendee_details = {
                    "name": context.userdata["userinfo"].name,
                    "email": context.userdata["userinfo"].email,
                    "timeZone": "Europe/Paris",
                }
                
                if slug not in self._event_ids:
                    raise Exception(f"Event type '{slug}' not found. Available: {list(self._event_ids.keys())}")
                
                payload = {
                    "start": time,
                    "eventTypeId": self._event_ids[slug],
                    "attendee": attendee_details,
                }

                params = {
                    "url": "https://api.cal.com/v2/bookings",
                    "json": payload,
                    "headers": headers,
                }

            elif request.value == "reschedule":
                payload = {"start": time}
                params = {
                    "url": f"https://api.cal.com/v2/bookings/{uid}/reschedule",
                    "headers": headers,
                    "json": payload,
                }

            else:
                raise Exception(f"Requête API non valide: {request}, {request.value}")
            
            # Exécuter la requête
            if request.value in ["schedule", "reschedule", "cancel"]:
                async with session.post(**params) as response:
                    data = await response.json()
                    print(f"DEBUG {request.value}: {data}")
            elif request.value in ["get_appts", "get_availability"]:
                async with session.get(**params) as response:
                    data = await response.json()
                    print(f"DEBUG {request.value}: {data}")
            else:
                raise Exception("Erreur de communication avec l'API Cal.com")
            return data

    @function_tool()
    async def check_availability(
        self,
        service_type: Annotated[
            str,
            Field(
                description="""Type de service :
                'diagnostic-piscine', 'entretien-piscine', 'reparation-piscine', ou 'installation-equipement'"""
            ),
        ],
        date: Annotated[
            str,
            Field(description="Date souhaitée au format ISO 8601 UTC")
        ],
        context: RunContext,
    ) -> str:
        """
        Vérifie la disponibilité pour un créneau donné et propose des alternatives.
        """
        try:
            response = await self.send_request(
                request=APIRequests.GET_AVAILABILITY, 
                time=date, 
                slug=service_type, 
                context=context
            )
            
            if response.get("status") == "success" and response.get("data"):
                return f"Le créneau {date} est disponible pour {service_type.replace('-', ' ')}."
            else:
                return f"Le créneau {date} n'est pas disponible. Proposez-moi un autre horaire : demain 8h, 10h, 14h, ou 16h ?"
                
        except Exception as e:
            print(f"ERROR checking availability: {e}")
            return "Je vais vérifier les créneaux disponibles. Préférez-vous plutôt demain matin (8h-12h) ou après-midi (14h-18h) ?"

    @function_tool()
    async def schedule_with_french_time(
        self,
        date_description: Annotated[str, Field(description="Description de la date en français (ex: 'demain', 'mardi', '17 juin')")],
        time_description: Annotated[str, Field(description="Heure souhaitée (ex: '10h', '14h30', 'matin', 'après-midi')")],
        service_type: Annotated[
            str,
            Field(
                description="""Type de service demandé :
                'diagnostic-piscine', 'entretien-piscine', 'reparation-piscine', ou 'installation-equipement'"""
            ),
        ],
        context: RunContext,
    ) -> str:
        """
        Planifie un rendez-vous en utilisant des expressions françaises de date et heure.
        Convertit automatiquement vers le format Cal.com et ENREGISTRE l'action.
        """
        # Vérifier que nous avons les informations client nécessaires
        userinfo = context.userdata["userinfo"]
        if not userinfo.name:
            return "Je dois d'abord connaître votre nom pour planifier le rendez-vous. Comment vous appelez-vous ?"
        
        # Générer email par défaut si manquant
        if not userinfo.email:
            email = f"{userinfo.name.lower().replace(' ', '.')}@client-piscinik.com"
            userinfo.email = email
            print(f"DEBUG: Email généré automatiquement: {email}")
        
        try:
            # Convertir la date/heure française vers ISO 8601 UTC
            conversion_result = await convert_french_time_to_iso(date_description, time_description)
            print(f"DEBUG: Conversion date: {conversion_result}")
            
            # Extraire le format ISO de la conversion
            iso_datetime = conversion_result.split("Format pour Cal.com : ")[1].strip()
            
            # Planifier le rendez-vous
            response = await self.send_request(
                request=APIRequests.SCHEDULE, 
                time=iso_datetime, 
                slug=service_type, 
                context=context
            )
            
            print(f"DEBUG Schedule response: {response}")
            
            # Vérifier les erreurs de date passée
            if isinstance(response, dict) and "statusCode" in response:
                if "Attempting to book a meeting in the past" in str(response):
                    # Enregistrer l'échec
                    await log_action(
                        "scheduler", 
                        "appointment_failed", 
                        f"Date dans le passé: {date_description} {time_description}", 
                        context
                    )
                    return f"La date '{date_description} {time_description}' semble être dans le passé. Pouvez-vous me proposer une date future ? (demain, après-demain, etc.)"
                elif "not available" in str(response).lower():
                    # Enregistrer l'indisponibilité
                    await log_action(
                        "scheduler", 
                        "appointment_unavailable", 
                        f"Créneau non disponible: {date_description} {time_description}", 
                        context
                    )
                    return f"Le créneau '{date_description} {time_description}' n'est pas disponible. Avez-vous une autre préférence ?"
                else:
                    await log_action(
                        "scheduler", 
                        "appointment_error", 
                        f"Erreur API: {response.get('message', 'Erreur inconnue')}", 
                        context
                    )
                    return f"Erreur de planification : {response.get('message', 'Erreur inconnue')}"
            
            # Vérifier le succès
            if isinstance(response, dict) and "status" in response:
                if response["status"] == "success":
                    # ENREGISTRER LE SUCCÈS
                    appointment_details = f"{service_type.replace('-', ' ')} le {date_description} à {time_description}"
                    await log_action(
                        "scheduler", 
                        "appointment_scheduled", 
                        appointment_details, 
                        context
                    )
                    return f"Parfait ! Votre rendez-vous pour {service_type.replace('-', ' ')} a été planifié avec succès le {date_description} à {time_description} !"
                elif response["status"] == "error":
                    error_msg = response.get('error', {}).get('message', 'Erreur inconnue')
                    if "not available" in error_msg.lower():
                        await log_action(
                            "scheduler", 
                            "appointment_unavailable", 
                            f"Créneau non disponible: {date_description} {time_description}", 
                            context
                        )
                        return f"Le créneau '{date_description} {time_description}' n'est pas disponible. Proposez-moi un autre horaire ?"
                    else:
                        await log_action(
                            "scheduler", 
                            "appointment_error", 
                            f"Erreur: {error_msg}", 
                            context
                        )
                        return f"Erreur lors de la planification : {error_msg}"
            
            await log_action(
                "scheduler", 
                "appointment_failed", 
                "Erreur inconnue lors de la planification", 
                context
            )
            return f"Erreur lors de la planification. Essayons un autre créneau ?"
            
        except Exception as e:
            print(f"ERROR in schedule_with_french_time: {e}")
            await log_action(
                "scheduler", 
                "appointment_error", 
                f"Exception: {str(e)}", 
                context
            )
            if "not found" in str(e):
                return f"Service '{service_type}' non configuré. Services disponibles : diagnostic, entretien, réparation, installation."
            return f"Erreur technique lors de la planification. Pouvez-vous me reproposer une date et heure ?"

    @function_tool()
    async def schedule(
        self,
        name: Annotated[str, Field(description="Le nom complet du client")],
        service_type: Annotated[
            str,
            Field(
                description="""Type de service demandé :
                'diagnostic-piscine', 'entretien-piscine', 'reparation-piscine', ou 'installation-equipement'"""
            ),
        ],
        date: Annotated[
            str,
            Field(
                description="""Date et heure formatées au format ISO 8601 UTC pour Cal.com.
                IMPORTANT: Utilisez schedule_with_french_time() pour les demandes en français."""
            ),
        ],
        context: RunContext,
    ) -> str:
        """
        Planifie un nouveau rendez-vous (version directe avec ISO 8601).
        Préférez schedule_with_french_time() pour les demandes en français.
        """
        context.userdata["userinfo"].name = name
        
        if not context.userdata["userinfo"].email:
            email = f"{name.lower().replace(' ', '.')}@client-piscinik.com"
            context.userdata["userinfo"].email = email
        
        try:
            response = await self.send_request(
                request=APIRequests.SCHEDULE, time=date, slug=service_type, context=context
            )
            
            print(f"DEBUG Schedule response: {response}")
            
            if isinstance(response, dict) and "statusCode" in response:
                if "Attempting to book a meeting in the past" in str(response):
                    await log_action("scheduler", "appointment_failed", "Date dans le passé", context)
                    return "La date sélectionnée est dans le passé. Veuillez choisir une date future."
                elif "not available" in str(response).lower():
                    await log_action("scheduler", "appointment_unavailable", f"Créneau {date} non disponible", context)
                    return "Ce créneau n'est pas disponible. Proposez-moi un autre horaire ?"
                else:
                    await log_action("scheduler", "appointment_error", f"Erreur: {response.get('message', 'Inconnue')}", context)
                    return f"Impossible de planifier : {response.get('message', 'Erreur inconnue')}"
            
            if isinstance(response, dict) and "status" in response:
                if response["status"] == "success":
                    # ENREGISTRER LE SUCCÈS
                    await log_action(
                        "scheduler", 
                        "appointment_scheduled", 
                        f"{service_type.replace('-', ' ')} à {date}", 
                        context
                    )
                    return f"Parfait ! Votre rendez-vous pour {service_type.replace('-', ' ')} a été planifié avec succès !"
                elif response["status"] == "error":
                    error_msg = response.get('error', {}).get('message', 'Erreur inconnue')
                    if "not available" in error_msg.lower():
                        await log_action("scheduler", "appointment_unavailable", f"Créneau {date} non disponible", context)
                        return "Ce créneau n'est pas disponible. Avez-vous une autre préférence ?"
                    else:
                        await log_action("scheduler", "appointment_error", f"Erreur: {error_msg}", context)
                        return f"Erreur lors de la planification : {error_msg}"
            
            await log_action("scheduler", "appointment_failed", "Erreur inconnue", context)
            return "Une erreur s'est produite. Proposez-moi un autre créneau ?"
            
        except Exception as e:
            print(f"ERROR in schedule: {e}")
            await log_action("scheduler", "appointment_error", f"Exception: {str(e)}", context)
            if "not found" in str(e):
                return f"Service '{service_type}' non configuré. Services disponibles : diagnostic, entretien, réparation, installation."
            return "Erreur technique. Essayons un autre créneau ?"

    @function_tool()
    async def cancel(
        self,
        email: Annotated[
            str, Field(description="L'email du client, au format partie-locale@domaine")
        ],
        context: RunContext,
    ) -> str:
        """
        Annule un rendez-vous existant pour les services de piscine.
        """
        context.userdata["userinfo"].email = email
        try:
            response = await self.send_request(request=APIRequests.GET_APPTS, context=context)
            if response.get("data"):
                cancel_response = await self.send_request(
                    request=APIRequests.CANCEL, uid=response["data"][0]["uid"], context=context
                )
                if cancel_response.get("status") == "success":
                    # ENREGISTRER L'ANNULATION
                    await log_action(
                        "scheduler", 
                        "appointment_cancelled", 
                        f"RDV annulé pour {email}", 
                        context
                    )
                    return "C'est fait ! Votre rendez-vous a été annulé avec succès."
                else:
                    await log_action("scheduler", "cancellation_failed", f"Échec annulation pour {email}", context)
                    return "Erreur lors de l'annulation. Pouvez-vous me donner plus de détails sur votre rendez-vous ?"
            else:
                await log_action("scheduler", "cancellation_failed", f"Aucun RDV trouvé pour {email}", context)
                return "Je ne trouve pas de rendez-vous à votre nom. Souhaitez-vous plutôt en planifier un ?"
        except Exception as e:
            print(f"ERROR in cancel: {e}")
            await log_action("scheduler", "cancellation_error", f"Exception: {str(e)}", context)
            return "Erreur lors de la recherche de votre rendez-vous. Vérifiez votre email ou contactez-nous directement."

    @function_tool()
    async def reschedule(
        self,
        email: Annotated[
            str, Field(description="L'email du client, au format partie-locale@domaine")
        ],
        new_time: Annotated[
            str,
            Field(description="La nouvelle date et heure pour le rendez-vous à replanifier"),
        ],
        context: RunContext,
    ) -> str:
        """
        Replanifie un rendez-vous à une nouvelle date spécifiée par le client.
        """
        context.userdata["userinfo"].email = email
        try:
            response = await self.send_request(request=APIRequests.GET_APPTS, context=context)
            if response.get("data"):
                reschedule_response = await self.send_request(
                    request=APIRequests.RESCHEDULE,
                    uid=response["data"][0]["uid"],
                    time=new_time,
                    context=context,
                )
                if reschedule_response.get("status") == "success":
                    # ENREGISTRER LA REPROGRAMMATION
                    await log_action(
                        "scheduler", 
                        "appointment_rescheduled", 
                        f"RDV reprogrammé pour {email} à {new_time}", 
                        context
                    )
                    return "Parfait ! Votre rendez-vous a été reprogrammé avec succès."
                elif "not available" in str(reschedule_response).lower():
                    await log_action("scheduler", "reschedule_unavailable", f"Créneau {new_time} non disponible", context)
                    return "Nous ne sommes pas disponibles à ce créneau. Proposez-moi un autre horaire ?"
                else:
                    await log_action("scheduler", "reschedule_failed", f"Échec reprogrammation pour {email}", context)
                    return "Erreur lors de la reprogrammation. Essayons un autre créneau ?"
            else:
                await log_action("scheduler", "reschedule_failed", f"Aucun RDV trouvé pour {email}", context)
                return "Je ne trouve pas de rendez-vous à votre nom. Souhaitez-vous plutôt en planifier un ?"
        except Exception as e:
            print(f"ERROR in reschedule: {e}")
            await log_action("scheduler", "reschedule_error", f"Exception: {str(e)}", context)
            return "Erreur lors de la reprogrammation. Pouvez-vous me proposer un autre créneau ?"