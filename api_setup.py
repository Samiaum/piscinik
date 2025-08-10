# api_setup.py - Version améliorée
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "cal-api-version": "2024-06-14",
    "Authorization": "Bearer " + os.getenv("CAL_API_KEY"),
}

SESSION_LENGTH = 60


async def get_event_id(slug: str) -> str | None:
    """Searches for an event type. Returns the event ID if found, None if not"""
    payload = {"username": os.getenv("CAL_API_USERNAME"), "eventSlug": slug}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.cal.com/v2/event-types", params=payload, headers=HEADERS
        ) as response:
            data = await response.json()
            print(f"DEBUG get_event_id for {slug}: {data}")  # Debug
            
            if data.get("status") == "success" and data.get("data"):
                return data["data"][0]["id"]
            elif data.get("status") == "error":
                print(f"ERROR retrieving event type {slug}: {data}")
                return None
            else:
                return None


async def search_schedule(name: str) -> str | None:
    """Checks if needed schedule already exists, returns schedule ID"""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.cal.com/v2/schedules/default", headers=HEADERS
        ) as response:
            data = await response.json()
            print(f"DEBUG search_schedule: {data}")  # Debug
            
            if (
                data.get("status") == "success"
                and data.get("data")
                and data["data"].get("name") == name
            ):
                return data["data"]["id"]
            else:
                return None


async def create_schedule() -> str:
    """Sets schedule for Piscinik, returns schedule ID"""
    payload = {
        "name": "Piscinik - Services Piscine",
        "timeZone": "Europe/Paris",
        "isDefault": True,
        "availability": [
            {
                "days": [
                    "Monday",
                    "Tuesday", 
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                ],
                "startTime": "08:00",
                "endTime": "12:00",
            },
            {
                "days": [
                    "Monday",
                    "Tuesday",
                    "Wednesday", 
                    "Thursday",
                    "Friday",
                    "Saturday",
                ],
                "startTime": "14:00",
                "endTime": "18:00",
            },
        ],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.cal.com/v2/schedules", json=payload, headers=HEADERS
        ) as response:
            data = await response.json()
            print(f"DEBUG create_schedule: {data}")  # Debug
            
            if data.get("status") == "success" and data.get("data"):
                return data["data"]["id"]
            else:
                raise Exception(f"Error creating schedule: {data}")


async def create_event_type(*, title: str, slug: str, schedule_id: str) -> str:
    """Creates specified event type and returns the event ID"""
    payload = {
        "lengthInMinutes": SESSION_LENGTH,
        "title": title,
        "slug": slug,
        "scheduleId": schedule_id,
        "description": f"Service Piscinik : {title}",
        "locations": [
            {
                "type": "inPerson",
                "address": "123 Avenue des Piscines, France"
            }
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.cal.com/v2/event-types", json=payload, headers=HEADERS
        ) as response:
            data = await response.json()
            print(f"DEBUG create_event_type {slug}: {data}")  # Debug
            
            if data.get("status") == "success":
                return data["data"]["id"]
            else:
                raise Exception(f"Error creating event type {slug}: {data}")


async def setup_event_types() -> dict:
    """Ensures that the schedule and event types are set up correctly in Cal.com for Piscinik.
    Returns a dictionary with event slugs and their respective IDs"""
    
    print("DEBUG: Starting setup_event_types...")
    
    # Vérifier et créer le planning
    schedule_id = await search_schedule("Piscinik - Services Piscine")
    if not schedule_id:
        print("DEBUG: Creating new schedule...")
        schedule_id = await create_schedule()
    else:
        print(f"DEBUG: Using existing schedule ID: {schedule_id}")

    event_ids = {}

    # Services Piscinik à créer
    services = [
        ("Diagnostic de Piscine", "diagnostic-piscine"),
        ("Entretien de Piscine", "entretien-piscine"), 
        ("Réparation de Piscine", "reparation-piscine"),
        ("Installation d'Équipement", "installation-equipement"),
    ]

    for title, slug in services:
        try:
            # Chercher l'événement existant
            event_id = await get_event_id(slug)
            if not event_id:
                print(f"DEBUG: Creating event type: {slug}")
                event_id = await create_event_type(
                    title=title, 
                    slug=slug, 
                    schedule_id=schedule_id
                )
            else:
                print(f"DEBUG: Using existing event ID for {slug}: {event_id}")
                
            event_ids[slug] = event_id
            
        except Exception as e:
            print(f"ERROR setting up event type {slug}: {e}")
            # Continuer avec les autres événements
            continue

    print(f"DEBUG: Final event_ids: {event_ids}")
    
    if not event_ids:
        raise Exception("No event types could be created! Check your Cal.com API credentials and permissions.")
    
    return event_ids