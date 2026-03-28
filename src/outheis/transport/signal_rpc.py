"""
Signal CLI JSON-RPC client.

Communicates with signal-cli via JSON-RPC protocol.

A dedicated reader thread owns all stdout reads and dispatches:
- receive events  → _receive_queue  (consumed by read_message)
- request responses → _response_map  (consumed by _send_request via Event)

This prevents the race condition that occurs when send_message and
read_message both try to readline() from the same stdout stream.
"""

from __future__ import annotations

import base64
import json
import queue
import subprocess
import threading
from dataclasses import dataclass


@dataclass
class SignalMessage:
    """Incoming Signal message."""
    sender_uuid: str
    sender_name: str
    sender_phone: str | None
    text: str
    timestamp: int  # Signal server timestamp (unique ID)
    is_voice: bool = False
    attachments: list[dict] | None = None


class SignalRPC:
    """
    JSON-RPC client for signal-cli.

    Starts signal-cli in jsonRpc mode and communicates via stdin/stdout.
    A single reader thread owns all stdout reads.
    """

    def __init__(self, phone: str):
        self.phone = phone
        self.process: subprocess.Popen | None = None
        self.request_id = 0
        self._stdin_lock = threading.Lock()

        # Reader thread dispatch targets
        self._receive_queue: queue.Queue = queue.Queue()
        self._response_map: dict[int, dict] = {}
        self._response_events: dict[int, threading.Event] = {}
        self._response_lock = threading.Lock()

        self._reader_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start signal-cli JSON-RPC process and the reader thread."""
        self.process = subprocess.Popen(
            ["signal-cli", "-a", self.phone, "jsonRpc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="signal-rpc-reader",
        )
        self._reader_thread.start()

    def stop(self) -> None:
        """Stop signal-cli process."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.process = None

    def _read_loop(self) -> None:
        """
        Owned by reader thread. Reads every line from stdout and routes it:
        - method == "receive"  →  _receive_queue
        - has "id"             →  _response_map + set Event
        """
        while self.process:
            try:
                line = self.process.stdout.readline()
            except Exception:
                break
            if not line:
                break  # EOF — process exited

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("method") == "receive":
                self._receive_queue.put(data)
            elif "id" in data:
                req_id = data["id"]
                with self._response_lock:
                    self._response_map[req_id] = data
                    event = self._response_events.get(req_id)
                if event:
                    event.set()

    def _send_request(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        """
        Send a JSON-RPC request and wait for the matching response.
        Thread-safe: stdin writes are locked; responses are dispatched by
        the reader thread.
        """
        if not self.process:
            raise RuntimeError("SignalRPC not started")

        with self._stdin_lock:
            self.request_id += 1
            req_id = self.request_id
            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }

            event = threading.Event()
            with self._response_lock:
                self._response_events[req_id] = event

            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()

        event.wait(timeout=timeout)

        with self._response_lock:
            self._response_events.pop(req_id, None)
            return self._response_map.pop(req_id, {})

    def subscribe(self) -> None:
        """Subscribe to receive messages."""
        self._send_request("subscribeReceive")

    def update_profile_name(self, name: str) -> None:
        """Set the bot's Signal display name."""
        try:
            self._send_request("updateProfile", {"name": name})
        except Exception as e:
            print(f"⚠️ updateProfile failed: {e}", flush=True)

    def read_message(self) -> SignalMessage | None:
        """
        Block until the next receive event arrives (put by reader thread).
        Returns None for envelopes that carry no user-facing text.
        """
        data = self._receive_queue.get()

        params = data.get("params", {})
        envelope = params.get("envelope", {})
        if not envelope:
            return None

        data_msg = envelope.get("dataMessage")
        sync_msg = envelope.get("syncMessage")

        # Skip sent-by-self sync messages
        if not data_msg or sync_msg:
            return None

        sender_uuid = envelope.get("sourceUuid", "")
        sender_name = envelope.get("sourceName", "Unknown")
        sender_phone = envelope.get("sourceNumber")
        message_text = data_msg.get("message") or ""
        timestamp = envelope.get("timestamp", 0)

        print(
            f"📨 Envelope: uuid={sender_uuid[:8] if sender_uuid else 'None'}... "
            f"phone={sender_phone} name={sender_name}",
            flush=True,
        )

        attachments = data_msg.get("attachments", [])
        is_voice = any(
            a.get("contentType", "").startswith("audio/")
            for a in attachments
        )

        return SignalMessage(
            sender_uuid=sender_uuid,
            sender_name=sender_name,
            sender_phone=sender_phone,
            text=message_text,
            timestamp=timestamp,
            is_voice=is_voice,
            attachments=attachments if attachments else None,
        )

    def send_message(self, recipient_uuid: str, text: str) -> None:
        """Send message to a recipient by UUID."""
        try:
            response = self._send_request("send", {
                "recipient": [recipient_uuid],
                "message": text,
            })
            if "error" in response:
                print(f"⚠️ send_message error: {response['error']}", flush=True)
        except Exception as e:
            print(f"⚠️ send_message failed: {e}", flush=True)

    def send_to_phone(self, phone: str, text: str) -> bool:
        """Send message to a recipient by phone number."""
        try:
            response = self._send_request("send", {
                "recipient": [phone],
                "message": text,
            })
            if "error" in response:
                print(f"⚠️ Send error: {response['error']}", flush=True)
                return False
            return True
        except Exception as e:
            print(f"⚠️ Send exception: {e}", flush=True)
            return False

    def get_user_id(self, phone: str) -> str | None:
        """Get UUID for a phone number."""
        try:
            response = self._send_request("getUserId", {"recipient": phone})
            result = response.get("result")
            if isinstance(result, dict):
                return result.get("uuid")
            return result
        except Exception:
            return None

    def get_attachment(self, attachment_id: str) -> bytes | None:
        """Download attachment data."""
        try:
            response = self._send_request("getAttachment", {"id": attachment_id})
            result = response.get("result")
            if isinstance(result, str):
                return base64.b64decode(result)
            elif isinstance(result, dict) and "data" in result:
                return base64.b64decode(result["data"])
            return None
        except Exception:
            return None
