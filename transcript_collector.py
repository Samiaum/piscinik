# transcript_collector.py - Enhanced with real-time webhooks
import aiohttp
import json
import os
import logging
import asyncio
from datetime import datetime, timezone
from livekit.agents import ConversationItemAddedEvent

# URLs for different webhook destinations
WEBHOOK_URL = os.getenv("TRANSCRIPTION_WEBHOOK_URL")  # Supabase (session end)
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")      # Make.com (real-time)
VOICEBOT_ID_ENV = os.getenv("VOICEBOT_ID")
log = logging.getLogger(__name__)

class TranscriptCollector:
    def __init__(self, session, job_ctx, userdata: dict):
        self._session = session
        self._job_ctx = job_ctx
        self._userdata = userdata
        self._messages = []
        self._started = datetime.now(timezone.utc)

        # Store room and participant info for phone extraction
        self._room_name = getattr(job_ctx.room, 'name', '') if hasattr(job_ctx, 'room') else ''
        self._participants = []

        # Real-time listener for each chat item
        session.on("conversation_item_added", self._on_msg_sync)
        # One-shot export when the session shuts down
        job_ctx.add_shutdown_callback(self._export)
        
        print("🎯 TranscriptCollector initialized with real-time webhooks")
        if MAKE_WEBHOOK_URL:
            print(f"📡 Real-time webhook: {MAKE_WEBHOOK_URL[:50]}...")
        if WEBHOOK_URL:
            print(f"📊 Session webhook: {WEBHOOK_URL[:50]}...")

    def _on_msg_sync(self, evt: ConversationItemAddedEvent):
        # Schedule the async handler without blocking
        asyncio.create_task(self._on_msg(evt))

    async def _on_msg(self, evt: ConversationItemAddedEvent):
        # Determine who spoke
        role = getattr(evt.item, "role", "unknown")
        # Extract text (use text_content helper if available)
        text = getattr(evt.item, "text_content", "") or ""
        if not text:
            raw = evt.item.content
            if isinstance(raw, list):
                text = " ".join(str(c) for c in raw if isinstance(c, str))
            else:
                text = str(raw or "")
        
        # Add to internal log
        message_data = {"role": role, "text": text, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._messages.append(message_data)
        
        # 🎯 REAL-TIME CONSOLE LOG
        timestamp = datetime.now().strftime("%H:%M:%S")
        if role == "user":
            print(f"👤 [{timestamp}] USER: {text}")
        elif role == "assistant":
            print(f"🤖 [{timestamp}] AGENT: {text}")
        else:
            print(f"💬 [{timestamp}] {role.upper()}: {text}")
        
        # 🎯 REAL-TIME WEBHOOK to Make.com (if configured)
        if MAKE_WEBHOOK_URL and text.strip():
            await self._send_realtime_webhook(role, text, message_data)

    async def _send_realtime_webhook(self, role: str, text: str, message_data: dict):
        """Send individual message to Make.com webhook in real-time"""
        try:
            phone_number = self._extract_phone_number()
            
            # Simplified payload for Make.com
            payload = {
                "event_type": "conversation_message",
                "voicebot_id": VOICEBOT_ID_ENV,
                "phone_number": phone_number,
                "timestamp": message_data["timestamp"],
                "role": role,
                "text": text,
                "session_started": self._started.isoformat(),
                "client_info": {
                    "name": getattr(self._userdata.get("userinfo", {}), 'name', None),
                    "email": getattr(self._userdata.get("userinfo", {}), 'email', None),
                    "pool_type": getattr(self._userdata.get("userinfo", {}), 'pool_type', None),
                }
            }
            
            # Simple headers for Make.com
            headers = {"Content-Type": "application/json"}
            
            async with aiohttp.ClientSession() as http:
                resp = await http.post(
                    MAKE_WEBHOOK_URL,
                    headers=headers,
                    data=json.dumps(payload, ensure_ascii=False),
                    timeout=5  # Quick timeout for real-time
                )
                if resp.status in (200, 201, 204):
                    log.debug(f"✅ Real-time webhook sent: {role} message")
                else:
                    log.warning(f"⚠️ Webhook failed: {resp.status}")
                    
        except Exception as e:
            log.error(f"❌ Real-time webhook error: {e}")

    def _extract_phone_number(self):
        """Extract phone number from available sources"""
        
        # Method 1: From userdata
        if "userinfo" in self._userdata and hasattr(self._userdata["userinfo"], "phone"):
            phone = self._userdata["userinfo"].phone
            if phone:
                return phone
        
        # Method 2: From room name pattern "ai-call-_+PHONE_RANDOM"
        if self._room_name and self._room_name.startswith("ai-call-_"):
            # Extract between "ai-call-_" and the last "_"
            parts = self._room_name[9:].split('_')  # Remove "ai-call-_" prefix
            if parts and parts[0].startswith('+'):
                log.info(f"Extracted phone from room name: {parts[0]}")
                return parts[0]
        
        # Method 3: From job context room participants
        try:
            if hasattr(self._job_ctx, 'room') and hasattr(self._job_ctx.room, 'remote_participants'):
                for participant in self._job_ctx.room.remote_participants.values():
                    identity = getattr(participant, 'identity', '')
                    if identity.startswith("sip_"):
                        phone = identity[4:]  # Remove "sip_" prefix
                        log.info(f"Extracted phone from participant identity: {phone}")
                        return phone
        except Exception as e:
            log.debug(f"Could not extract from participants: {e}")
        
        # Method 4: Check if room name contains phone in different format
        if self._room_name:
            # Look for phone patterns in room name
            import re
            phone_match = re.search(r'\+\d{10,15}', self._room_name)
            if phone_match:
                phone = phone_match.group()
                log.info(f"Extracted phone from room name regex: {phone}")
                return phone
        
        log.warning("Could not extract phone number from any source")
        return "unknown"

    async def _export(self, reason):
        # Skip if no endpoint configured
        if not WEBHOOK_URL:
            log.warning("No TRANSCRIPTION_WEBHOOK_URL set; skipping export")
            return
        
        # Skip if nothing to send
        if not self._messages:
            log.info("No messages to export; skipping")
            return

        ended = datetime.now(timezone.utc)
        duration = int((ended - self._started).total_seconds())
        
        # Debug information
        log.info(f"DEBUG userdata: {self._userdata}")
        log.info(f"DEBUG room_name: {self._room_name}")
        
        # Extract phone number
        phone_number = self._extract_phone_number()
        log.info(f"DEBUG final phone_number: {phone_number}")
        
        # Build the payload with Piscinik-specific data
        payload = {
            "p_voicebot_id": VOICEBOT_ID_ENV,
            "p_phone_number": phone_number,
            "p_started_at": self._started.isoformat(),
            "p_ended_at": ended.isoformat(),
            "p_credits_used": duration,
            "p_duration": duration,
            "p_transcription": self._messages,
            "p_service_type": "piscinik",  # Identifier for pool services
            "p_client_info": {
                "name": getattr(self._userdata.get("userinfo", {}), 'name', None),
                "email": getattr(self._userdata.get("userinfo", {}), 'email', None),
                "pool_type": getattr(self._userdata.get("userinfo", {}), 'pool_type', None),
                "pool_size": getattr(self._userdata.get("userinfo", {}), 'pool_size', None),
            }
        }

        # Supabase RPC requires both apikey and Authorization headers
        headers = {
            "apikey": os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_ROLE_KEY')}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as http:
            try:
                resp = await http.post(
                    WEBHOOK_URL,
                    headers=headers,
                    data=json.dumps(payload, ensure_ascii=False),
                )
                if resp.status not in (200, 201, 204):
                    err = await resp.text()
                    log.error("Supabase RPC failed %s: %s", resp.status, err)
                else:
                    log.info("✅ Successfully exported Piscinik transcript to Supabase")
                    print(f"📊 Session exported: {len(self._messages)} messages, {duration}s duration")
            except Exception:
                log.exception("Error calling Supabase RPC")