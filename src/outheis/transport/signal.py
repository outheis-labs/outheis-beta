"""
Signal transport.

Receives messages from Signal via signal-cli JSON-RPC,
writes to messages.jsonl, watches for responses, sends back.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from outheis.core.config import Config, get_messages_path
from outheis.core.message import Message, create_user_message
from outheis.core.queue import append, read_last_n
from outheis.transport.base import Transport
from outheis.transport.signal_rpc import SignalRPC, SignalMessage


class SignalTransport(Transport):
    """
    Signal Messenger transport.
    
    Runs two threads:
    - Main thread: receives Signal messages, writes to queue
    - Watcher thread: monitors queue for responses, sends back via Signal
    """
    
    name = "signal"
    
    def __init__(self, config: Config):
        """
        Args:
            config: outheis configuration
        """
        self.config = config
        
        # Validate config
        if not config.signal or not config.signal.bot_phone:
            raise ValueError("signal.bot_phone not configured")
        if not config.human.phone:
            raise ValueError("human.phone not configured")
        
        self.bot_phone = config.signal.bot_phone
        
        # Build allowed phones: human phones + signal.allowed
        self.allowed_phones: dict[str, str] = {}  # phone -> name
        for phone in config.human.phone:
            self.allowed_phones[phone] = config.human.name
        for contact in config.signal.allowed:
            self.allowed_phones[contact.phone] = contact.name
        
        # Load learned UUIDs from persistent storage
        self.known_uuids: dict[str, str] = self._load_known_uuids()  # phone -> uuid
        
        self.rpc = SignalRPC(self.bot_phone)
        self.queue_path = get_messages_path()
        
        # Pending responses: {message_id: sender_uuid}
        self.pending: dict[str, str] = {}
        self._lock = threading.Lock()
        
        # Watcher thread control
        self._watching = False
        self._watcher_thread: threading.Thread | None = None
        
        # Optional: Whisper for voice
        self.whisper_model = None
        self._init_whisper()
    
    def _get_signal_state_path(self) -> Path:
        """Get path to signal state file."""
        from outheis.core.config import get_human_dir
        return get_human_dir() / "signal.json"
    
    def _load_known_uuids(self) -> dict[str, str]:
        """Load known phone->UUID mappings from persistent storage."""
        import json
        path = self._get_signal_state_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                # Handle old format (single user_uuid)
                if "user_uuid" in data:
                    phone = data.get("user_phone", "")
                    if phone:
                        return {phone: data["user_uuid"]}
                # New format
                return data.get("known_uuids", {})
            except Exception:
                pass
        return {}
    
    def _save_known_uuids(self) -> None:
        """Save phone->UUID mappings to persistent storage."""
        import json
        path = self._get_signal_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"known_uuids": self.known_uuids}
        path.write_text(json.dumps(data, indent=2))
    
    def _init_whisper(self) -> None:
        """Initialize Whisper for voice transcription (optional)."""
        try:
            from faster_whisper import WhisperModel
            print("🎤 Loading Whisper model...", flush=True)
            self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            print("✓ Whisper loaded", flush=True)
        except ImportError:
            print("ℹ️  Whisper not available (install faster-whisper for voice)", flush=True)
    
    def _is_allowed(self, msg: SignalMessage) -> bool:
        """Check if sender is allowed (human.phone + signal.allowed)."""
        # Check if UUID is in known mappings
        if msg.sender_uuid in self.known_uuids.values():
            return True
        
        # Check phone number — learn and save UUID
        if msg.sender_phone and msg.sender_phone in self.allowed_phones:
            self.known_uuids[msg.sender_phone] = msg.sender_uuid
            self._save_known_uuids()
            name = self.allowed_phones[msg.sender_phone]
            print(f"📝 Learned UUID for {name} ({msg.sender_phone}): {msg.sender_uuid[:8]}...", flush=True)
            return True
        
        # First-time setup: no UUIDs known yet, accept first message
        # Only if it could be the human (we don't know which phone they're using)
        if not self.known_uuids and msg.sender_uuid:
            # Use first configured phone as placeholder
            first_phone = next(iter(self.allowed_phones.keys()), "unknown")
            self.known_uuids[first_phone] = msg.sender_uuid
            self._save_known_uuids()
            print(f"📝 First contact — saved UUID: {msg.sender_uuid[:8]}...", flush=True)
            return True
        
        return False
    
    def _transcribe_voice(self, audio_data: bytes) -> str | None:
        """Transcribe voice message with Whisper."""
        if not self.whisper_model:
            return None
        
        import tempfile
        
        try:
            # Write to temp file
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name
            
            # Transcribe
            segments, _ = self.whisper_model.transcribe(
                temp_path,
                language="de",  # TODO: from config.human.language
                beam_size=5,
            )
            
            text = " ".join(s.text.strip() for s in segments)
            
            # Cleanup
            Path(temp_path).unlink(missing_ok=True)
            
            return text if text else None
            
        except Exception as e:
            print(f"⚠️ Transcription error: {e}", flush=True)
            return None
    
    def send(self, text: str) -> Message:
        """Create and queue a user message."""
        msg = create_user_message(
            text=text,
            channel="signal",
            identity=self.user_phone or "signal_user",
        )
        append(self.queue_path, msg)
        return msg
    
    def wait_for_response(self, message_id: str, timeout: float = 30.0) -> Message | None:
        """Wait for a response (used internally by watcher)."""
        start = time.time()
        
        while time.time() - start < timeout:
            messages = read_last_n(self.queue_path, 20)
            
            for msg in messages:
                if (
                    msg.reply_to == message_id
                    and msg.to == "transport"
                    and msg.from_agent
                ):
                    return msg
            
            time.sleep(0.5)
        
        return None
    
    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove markdown markup, preserve structure, emojis, and content."""
        import re
        # Bold and italic
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        # Headings: ## Heading → Heading (keep the line, strip # prefix)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Inline code
        text = re.sub(r'`(.+?)`', r'\1', text)
        # Horizontal rules: --- → 〰️〰️〰️
        text = re.sub(r'^---+$', '〰️{20}', text, flags=re.MULTILINE)
        # Remaining underscore sequences used as dividers (e.g. from Daily.md)
        text = re.sub(r'^_{10,}$', '〰️{20}', text, flags=re.MULTILINE)
        # Checkboxes: - [x] → ☑️, - [ ] → 🟩
        text = re.sub(r'^(\s*)-\s+\[[xX]\]\s+', r'\1☑️ ', text, flags=re.MULTILINE)
        text = re.sub(r'^(\s*)-\s+\[ \]\s+', r'\1🟩 ', text, flags=re.MULTILINE)
        # Remaining bullet points
        text = re.sub(r'^(\s*)[-*]\s+', r'\1', text, flags=re.MULTILINE)
        return text

    def _watch_responses(self) -> None:
        """Watcher thread: check for responses and send back via Signal."""
        sent_interim_ids: set[str] = set()
        sent_broadcast_ids: set[str] = set()

        while self._watching:
            time.sleep(1)  # Check every second

            with self._lock:
                pending_copy = dict(self.pending)

            # Check for responses and broadcasts
            messages = read_last_n(self.queue_path, 30)

            for msg in messages:
                # Broadcast notifications (system alerts, fallback mode, etc.)
                if msg.to == "transport" and msg.intent == "broadcast" and msg.id not in sent_broadcast_ids:
                    text = msg.payload.get("text", "")
                    if text and self.user_phone:
                        try:
                            self.rpc.send_to_phone(self.user_phone, self._strip_markdown(text))
                            sent_broadcast_ids.add(msg.id)
                            print(f"📢 Sent broadcast to Signal", flush=True)
                        except Exception as e:
                            print(f"⚠️ Failed to send broadcast: {e}", flush=True)

            if not pending_copy:
                continue

            for msg in messages:
                if msg.reply_to in pending_copy and msg.to == "transport":
                    is_interim = msg.intent == "interim"

                    if is_interim and msg.id in sent_interim_ids:
                        continue

                    sender_uuid = pending_copy[msg.reply_to]
                    response_text = msg.payload.get("text", "")

                    if response_text:
                        try:
                            self.rpc.send_message(sender_uuid, self._strip_markdown(response_text))
                            if is_interim:
                                sent_interim_ids.add(msg.id)
                                print(f"📤 Sent interim to Signal", flush=True)
                            else:
                                print(f"📤 Sent response to Signal", flush=True)
                        except Exception as e:
                            print(f"⚠️ Failed to send: {e}", flush=True)

                    # Only remove from pending on final response
                    if not is_interim:
                        with self._lock:
                            self.pending.pop(msg.reply_to, None)
    
    def _handle_message(self, msg: SignalMessage) -> None:
        """Handle incoming Signal message."""
        # Check authorization
        if not self._is_allowed(msg):
            print(f"⚠️ Unauthorized: {msg.sender_phone}", flush=True)
            return
        
        text = msg.text
        
        # Handle voice message
        if msg.is_voice and msg.attachments:
            print("🎤 Voice message, transcribing...", flush=True)
            
            voice_att = next(
                (a for a in msg.attachments if a.get("contentType", "").startswith("audio/")),
                None
            )
            
            if voice_att and voice_att.get("id"):
                audio_data = self.rpc.get_attachment(voice_att["id"])
                if audio_data:
                    transcribed = self._transcribe_voice(audio_data)
                    if transcribed:
                        print(f"✓ Transcribed: {transcribed[:50]}...", flush=True)
                        text = transcribed
        
        if not text.strip():
            return
        
        print(f"📩 {msg.sender_name}: {text[:60]}{'...' if len(text) > 60 else ''}", flush=True)
        
        # Create message and add to queue
        user_msg = create_user_message(
            text=text,
            channel="signal",
            identity=msg.sender_phone or msg.sender_uuid,
        )
        append(self.queue_path, user_msg)
        
        # Track for response
        with self._lock:
            self.pending[user_msg.id] = msg.sender_uuid
        
        print(f"💬 Queued [{user_msg.id[:8]}], waiting for response...", flush=True)
    
    def run(self) -> None:
        """Run Signal transport main loop."""
        print("\n" + "=" * 50)
        print("Signal Transport")
        print("=" * 50)
        print(f"Bot phone: {self.bot_phone}")
        print(f"Allowed: {len(self.allowed_phones)} contacts")
        for phone, name in self.allowed_phones.items():
            print(f"  • {name}: {phone}")
        print(f"Voice: {'✓' if self.whisper_model else '✗'}")
        print("=" * 50 + "\n")
        
        try:
            # Start RPC
            print("Starting signal-cli...", flush=True)
            self.rpc.start()
            self.rpc.subscribe()
            if self.config.signal.bot_name:
                self.rpc.update_profile_name(self.config.signal.bot_name)
                print(f"✓ Profile name set: {self.config.signal.bot_name}", flush=True)
            print("✓ signal-cli connected", flush=True)

            # Show known UUIDs
            if self.known_uuids:
                print(f"✓ Known users: {len(self.known_uuids)}", flush=True)
                for phone, uuid in self.known_uuids.items():
                    print(f"  • {phone}: {uuid[:8]}...", flush=True)
            else:
                print("⏳ No known UUIDs — first message will be accepted", flush=True)

            # Start watcher thread
            self._watching = True
            self._watcher_thread = threading.Thread(target=self._watch_responses, daemon=True)
            self._watcher_thread.start()
            print("✓ Response watcher started", flush=True)

            print("\n👂 Listening for Signal messages...\n")

            while True:
                msg = self.rpc.read_message()
                if msg:
                    self._handle_message(msg)

        except KeyboardInterrupt:
            print("\n\n👋 Signal Transport shutting down...")
        except Exception as e:
            import traceback
            print(f"\n❌ Signal transport crashed: {e}", flush=True)
            traceback.print_exc()
        finally:
            self._watching = False
            self.rpc.stop()
