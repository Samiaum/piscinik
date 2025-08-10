# piscinik_agent.py
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from api_setup import setup_event_types
from dotenv import load_dotenv
from pydantic import BaseModel
from tasks import Messenger, Receptionist, Scheduler, TechnicalExpert
from transcript_collector import TranscriptCollector  # Enhanced version with real-time logging
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    RoomInputOptions,
    RoomOutputOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import aws
import openai

# Clean logging setup
logging.basicConfig(level=logging.INFO, format='%(message)s')
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)

class UserInfo(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    message: str | None = None
    pool_type: str | None = None  # Type de piscine
    pool_size: str | None = None  # Taille de la piscine

class SessionHistory(BaseModel):
    """Historique des actions de la session pour éviter les redondances."""
    actions: list[dict] = []
    last_agent: str | None = None
    session_start: str | None = None
    last_action_time: str | None = None

@dataclass
class Agents:
    @property
    def receptionist(self) -> Agent:
        return Receptionist()
    
    @property
    def messenger(self) -> Agent:
        return Messenger()
    
    @property
    def technical_expert(self) -> Agent:
        return TechnicalExpert()
    
    def scheduler(self, service: str) -> Agent:
        return Scheduler(service=service)

load_dotenv()

# Configuration AWS et OpenAI
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
VOICE_MODEL = os.getenv("NOVA_SONIC_VOICE", "ambre")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "10000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

logger = logging.getLogger("piscinik-scheduler")
logger.setLevel(logging.INFO)

async def entrypoint(ctx: JobContext):
    # 1) Set up your Cal.com event types for Piscinik
    event_ids = await setup_event_types()
    
    # 2) Initialize session with memory capabilities
    userdata = {
        "event_ids": event_ids,
        "userinfo": UserInfo(),
        "agents": Agents(),
        "session_history": SessionHistory(
            session_start=datetime.now().isoformat(),
            actions=[],
            last_agent=None,
            last_action_time=None
        ),
    }
    
    # Enhanced session logging
    session_time = userdata['session_history'].session_start
    print(f"📅 Piscinik Session Started: {session_time}")
    print(f"🎯 Available Services: {list(event_ids.keys())}")
    print(f"🏊‍♂️ Pool Service Bot Ready")
    
    # 3) Build the AgentSession with AWS Nova Sonic
    session = AgentSession(
        userdata=userdata,
        llm=aws.realtime.RealtimeModel(
            voice=VOICE_MODEL,
            region=AWS_REGION,
            tool_choice="auto",
            max_tokens=MAX_TOKENS,
        ),
    )
    
    # 4) Connection event logging
    @ctx.room.on("participant_connected")
    def on_participant_connected(participant):
        name = participant.name or participant.identity or 'Client'
        print(f"🔌 Client Connected: {name}")
        print("🗣️  Starting conversation...")
    
    @ctx.room.on("participant_disconnected") 
    def on_participant_disconnected(participant):
        name = participant.name or participant.identity or 'Client'
        print(f"🔌 Client Disconnected: {name}")
        print("📞 Call ended")
    
    # 5) Attach the enhanced transcript collector (with real-time logging + webhooks)
    TranscriptCollector(session, ctx, userdata)
    
    print("🚀 Piscinik Agent Ready - Real-time logging enabled")
    
    # 6) Connect to LiveKit and start the conversation
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await session.start(
        agent=userdata["agents"].receptionist,
        room=ctx.room,
        room_input_options=RoomInputOptions(),
        room_output_options=RoomOutputOptions(
            audio_enabled=True,
            transcription_enabled=True,
        ),
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
