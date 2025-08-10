# tasks/global_functions.py
from datetime import date, datetime, timedelta
from typing import Annotated
from pydantic import Field
from livekit.agents.llm import function_tool
from livekit.agents.voice import Agent, RunContext

# ===== FONCTIONS DE MÉMOIRE DE SESSION =====

@function_tool()
async def log_action(
    agent_name: Annotated[str, Field(description="Nom de l'agent qui effectue l'action")],
    action_type: Annotated[str, Field(description="Type d'action : 'appointment_scheduled', 'appointment_cancelled', 'message_sent', 'technical_advice', etc.")],
    details: Annotated[str, Field(description="Détails de l'action au format JSON ou texte descriptif")],
    context: RunContext,
) -> str:
    """
    Enregistre une action dans l'historique de session pour éviter les redondances.
    """
    session_history = context.userdata["session_history"]
    
    action_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "action": action_type,
        "details": details
    }
    
    # Ajouter l'action à l'historique
    session_history.actions.append(action_entry)
    session_history.last_agent = agent_name
    session_history.last_action_time = action_entry["timestamp"]
    
    # Limiter l'historique aux 10 dernières actions pour optimiser la performance
    if len(session_history.actions) > 10:
        session_history.actions = session_history.actions[-10:]
    
    print(f"DEBUG: Action logged - {agent_name}: {action_type}")
    return f"Action enregistrée : {action_type}"

@function_tool()
async def get_recent_actions(
    context: RunContext,
    limit: Annotated[int, Field(description="Nombre d'actions récentes à récupérer")] = 3,
) -> str:
    """
    Récupère les actions récentes de la session pour contextualiser la conversation.
    """
    session_history = context.userdata["session_history"]
    
    if not session_history.actions:
        return "Aucune action récente dans cette session."
    
    # Récupérer les dernières actions
    recent_actions = session_history.actions[-limit:]
    
    summary = "Actions récentes dans cette session :\n"
    for action in recent_actions:
        timestamp = datetime.fromisoformat(action["timestamp"])
        time_str = timestamp.strftime("%H:%M")
        summary += f"- {time_str} | {action['agent']} : {action['action']} - {action['details']}\n"
    
    return summary.strip()

@function_tool()
async def check_recent_appointment(
    context: RunContext,
) -> str:
    """
    Vérifie si un rendez-vous a été planifié récemment dans cette session.
    Retourne les détails du dernier RDV ou 'None' si aucun.
    """
    session_history = context.userdata["session_history"]
    
    # Chercher la dernière action de type appointment
    for action in reversed(session_history.actions):
        if action["action"] in ["appointment_scheduled", "appointment_cancelled", "appointment_rescheduled"]:
            return f"Dernier RDV : {action['action']} - {action['details']} (à {datetime.fromisoformat(action['timestamp']).strftime('%H:%M')})"
    
    return "None"

@function_tool()
async def clear_session_history(
    context: RunContext,
) -> str:
    """
    Remet à zéro l'historique de session (utile pour les tests ou nouveau client).
    """
    session_history = context.userdata["session_history"]
    session_history.actions = []
    session_history.last_agent = None
    session_history.last_action_time = None
    
    return "Historique de session réinitialisé."

# ===== FONCTIONS EXISTANTES =====

@function_tool()
async def update_information(
    field: Annotated[
        str,
        Field(
            description="""Le type d'information à mettre à jour,
            parmi 'phone_number', 'email', 'name', 'pool_type', ou 'pool_size'"""
        ),
    ],
    info: Annotated[str, Field(description="La nouvelle information fournie par l'utilisateur")],
    context: RunContext,
) -> str:
    """
    Met à jour les informations enregistrées sur l'utilisateur.
    RETOURNE un message contextuel selon l'agent qui l'utilise.
    """
    userinfo = context.userdata["userinfo"]
    session_history = context.userdata["session_history"]
    
    # Mettre à jour l'information
    if field == "name":
        userinfo.name = info
    elif field == "phone_number":
        userinfo.phone = info
    elif field == "email":
        userinfo.email = info
    elif field == "pool_type":
        userinfo.pool_type = info
    elif field == "pool_size":
        userinfo.pool_size = info
    
    # 🎯 CORRECTION : Message contextuel selon l'historique récent
    recent_appointment = None
    for action in reversed(session_history.actions):
        if action["action"] == "appointment_scheduled":
            recent_appointment = action
            break
    
    # Si un RDV vient d'être planifié ET qu'on met à jour l'email
    if recent_appointment and field == "email":
        # Vérifier que le RDV est très récent (moins de 2 minutes)
        from datetime import datetime
        action_time = datetime.fromisoformat(recent_appointment["timestamp"])
        now = datetime.now()
        time_diff = (now - action_time).total_seconds()
        
        if time_diff < 120:  # Moins de 2 minutes
            return f"Parfait ! Votre rendez-vous pour {recent_appointment['details']} est confirmé avec votre email {info} !"
    
    # Message par défaut (seulement si pas de contexte RDV récent)
    return f"Parfait, votre {field.replace('_', ' ')} a été enregistré !"



@function_tool()
async def get_user_info(
    field: Annotated[
        str,
        Field(
            description="""Le type d'information à récupérer,
            parmi 'phone_number', 'email', 'name', 'pool_type', ou 'pool_size'"""
        ),
    ],
    context: RunContext,
) -> str:
    """
    Récupère les informations enregistrées sur l'utilisateur.
    Les champs disponibles sont : nom, numéro de téléphone, email, type de piscine, et taille de piscine.
    """
    userinfo = context.userdata["userinfo"]
    if field == "name" and userinfo.name:
        return userinfo.name
    elif field == "phone_number" and userinfo.phone:
        return userinfo.phone
    elif field == "email" and userinfo.email:
        return userinfo.email
    elif field == "pool_type" and userinfo.pool_type:
        return userinfo.pool_type
    elif field == "pool_size" and userinfo.pool_size:
        return userinfo.pool_size
    else:
        return "Information non fournie"

@function_tool()
async def transfer_to_receptionist(context: RunContext) -> tuple[Agent, str]:
    """Transfère l'utilisateur vers la réceptionniste pour toute demande générale
    ou quand ils ont terminé de gérer leurs rendez-vous."""
    return context.userdata["agents"].receptionist, "Je vous transfère vers notre réceptionniste !"

@function_tool()
async def transfer_to_scheduler(
    action: Annotated[
        str,
        Field(
            description="""L'action demandée pour le rendez-vous,
            parmi 'planifier', 'replanifier', ou 'annuler'"""
        ),
    ],
    context: RunContext,
) -> tuple[Agent, str]:
    """
    Transfère l'utilisateur vers le planificateur pour gérer les rendez-vous.
    """
    return context.userdata["agents"].scheduler(
        service=action
    ), "Je vous transfère vers notre planificateur !"

@function_tool()
async def transfer_to_messenger(context: RunContext) -> tuple[Agent, str]:
    """
    Transfère l'utilisateur vers le service de messagerie s'ils veulent laisser un message.
    """
    return context.userdata["agents"].messenger, "Je vous transfère vers notre service de messagerie !"

@function_tool()
async def transfer_to_technical_expert(context: RunContext) -> tuple[Agent, str]:
    """
    Transfère l'utilisateur vers l'expert technique pour les questions sur l'entretien,
    les équipements, ou les problèmes techniques de piscine.
    """
    return context.userdata["agents"].technical_expert, "Je vous transfère vers notre expert technique !"

@function_tool()
async def get_date_today() -> str:
    """
    Récupère la date actuelle RÉELLE au format ISO (YYYY-MM-DD).
    """
    return date.today().isoformat()  # Retourne la vraie date système

@function_tool()
async def get_current_datetime_info() -> str:
    """
    Récupère les informations complètes sur la date et heure actuelles RÉELLES.
    Utile pour calculer les dates relatives comme "demain", "après-demain".
    """
    now = datetime.now()
    today = now.date()  # Date système réelle
    
    # Calculer les jours de la semaine dynamiquement
    weekday_names = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
    current_weekday = weekday_names[today.weekday()]
    
    date_info = f"""Date actuelle : {today.isoformat()} ({current_weekday} {today.day} {today.strftime('%B')} {today.year})
Demain : {(today + timedelta(days=1)).isoformat()} ({weekday_names[(today.weekday() + 1) % 7]})
Après-demain : {(today + timedelta(days=2)).isoformat()} ({weekday_names[(today.weekday() + 2) % 7]})

Heure actuelle : {now.strftime('%H:%M')}

Pour les rendez-vous, utilisez le format ISO 8601 UTC :
- Exemple demain 10h : {(today + timedelta(days=1)).isoformat()}T08:00:00.000Z (10h Paris = 8h UTC)
- Exemple après-demain 14h : {(today + timedelta(days=2)).isoformat()}T12:00:00.000Z (14h Paris = 12h UTC)"""
    
    return date_info

@function_tool()
async def convert_french_time_to_iso(
    date_description: Annotated[str, Field(description="Description de la date en français (ex: 'demain', 'mardi', '17 juin')")],
    time_description: Annotated[str, Field(description="Heure souhaitée (ex: '10h', '14h30', 'matin', 'après-midi')")],
) -> str:
    """
    Convertit une date et heure en français vers le format ISO 8601 UTC pour Cal.com.
    Utilise la date système RÉELLE comme référence.
    """
    today = date.today()  # Date système RÉELLE
    current_weekday = today.weekday()  # 0=lundi, 1=mardi, ..., 6=dimanche
    
    # Mapping des jours de la semaine
    weekdays = {
        'lundi': 0, 'mardi': 1, 'mercredi': 2, 'jeudi': 3, 
        'vendredi': 4, 'samedi': 5, 'dimanche': 6
    }
    
    target_date = today
    date_lower = date_description.lower()
    
    # Gestion des expressions relatives simples
    if "demain" in date_lower:
        target_date = today + timedelta(days=1)
    elif "après-demain" in date_lower or "aprés-demain" in date_lower:
        target_date = today + timedelta(days=2)
    elif "aujourd'hui" in date_lower or "aujourd hui" in date_lower:
        target_date = today
    
    # Gestion dynamique des jours de la semaine
    else:
        found_day = None
        is_next_week = "prochain" in date_lower or "prochaine" in date_lower
        
        # Chercher le jour mentionné
        for day_name, day_num in weekdays.items():
            if day_name in date_lower:
                found_day = day_num
                break
        
        if found_day is not None:
            # Calculer combien de jours jusqu'au prochain occurrence de ce jour
            days_ahead = found_day - current_weekday
            
            if is_next_week or days_ahead <= 0:
                # Si c'est "prochain" ou si le jour est déjà passé cette semaine
                days_ahead += 7
            
            target_date = today + timedelta(days=days_ahead)
    
    # Gestion des dates numériques (ex: "17 juin", "19")
    import re
    date_numbers = re.findall(r'\b(\d{1,2})\b', date_description)
    if date_numbers:
        day_num = int(date_numbers[0])
        # Si le numéro est supérieur au jour actuel ce mois, l'utiliser
        if day_num > today.day:
            try:
                target_date = today.replace(day=day_num)
            except ValueError:
                # Jour invalide pour ce mois, utiliser le mois suivant
                if today.month == 12:
                    target_date = today.replace(year=today.year + 1, month=1, day=day_num)
                else:
                    target_date = today.replace(month=today.month + 1, day=day_num)
        elif day_num <= today.day:
            # Jour dans le passé ce mois, essayer le mois suivant
            try:
                if today.month == 12:
                    target_date = today.replace(year=today.year + 1, month=1, day=day_num)
                else:
                    target_date = today.replace(month=today.month + 1, day=day_num)
            except ValueError:
                # Si ça échoue, utiliser le calcul par défaut
                target_date = today + timedelta(days=7)
    
    # Mapping des heures (France = UTC+1 en hiver, UTC+2 en été)
    # En juin, nous sommes en UTC+2 (heure d'été)
    hour_utc = 9  # Par défaut 11h Paris = 9h UTC
    time_lower = time_description.lower()
    
    if "8h" in time_lower or "8:" in time_lower:
        hour_utc = 6  # 8h Paris = 6h UTC
    elif "9h" in time_lower or "9:" in time_lower:
        hour_utc = 7  # 9h Paris = 7h UTC
    elif "10h" in time_lower or "10:" in time_lower:
        hour_utc = 8  # 10h Paris = 8h UTC
    elif "11h" in time_lower or "11:" in time_lower:
        hour_utc = 9  # 11h Paris = 9h UTC
    elif "14h" in time_lower or "14:" in time_lower:
        hour_utc = 12  # 14h Paris = 12h UTC
    elif "15h" in time_lower or "15:" in time_lower:
        hour_utc = 13  # 15h Paris = 13h UTC
    elif "16h" in time_lower or "16:" in time_lower:
        hour_utc = 14  # 16h Paris = 14h UTC
    elif "matin" in time_lower:
        hour_utc = 8  # 10h Paris = 8h UTC
    elif "après-midi" in time_lower or "aprés-midi" in time_lower:
        hour_utc = 12  # 14h Paris = 12h UTC
    
    # Format ISO 8601 UTC pour Cal.com
    iso_datetime = f"{target_date.isoformat()}T{hour_utc:02d}:00:00.000Z"
    
    return f"""Date convertie : {iso_datetime}
Détail : {target_date.strftime('%A %d %B %Y')} à {hour_utc + 2}h (heure française)
Format pour Cal.com : {iso_datetime}"""