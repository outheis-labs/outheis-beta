"""
CLI transport.

Handles command-line interaction with outheis.
"""

from __future__ import annotations

from outheis.core.config import get_messages_path
from outheis.core.message import Message, create_user_message
from outheis.core.queue import append, read_last_n

# =============================================================================
# CLI TRANSPORT
# =============================================================================

class CLITransport:
    """
    Command-line transport.

    Sends user messages to the queue and displays responses.
    """

    def __init__(self, identity: str = "cli_user"):
        self.identity = identity
        self.queue_path = get_messages_path()
        self.current_conversation: str | None = None

    def send(self, text: str) -> Message:
        """Send a message and return it."""
        msg = create_user_message(
            text=text,
            channel="cli",
            identity=self.identity,
            conversation_id=self.current_conversation,
        )

        # Update current conversation
        self.current_conversation = msg.conversation_id

        # Append to queue
        append(self.queue_path, msg)

        return msg

    def check_for_response(self, message_id: str) -> Message | None:
        """
        Check once for a response to a message.
        
        Non-blocking single check.
        """
        messages = read_last_n(self.queue_path, 10)

        for msg in messages:
            if (
                msg.reply_to == message_id
                and msg.to == "transport"
                and msg.from_agent
            ):
                return msg

        return None

    def wait_for_response(
        self,
        message_id: str,
        timeout: float = 30.0,
    ) -> Message | None:
        """
        Wait for a response to a message.

        Polls the queue for a response message. Interim notifications
        (intent="interim") are displayed immediately but polling continues.
        """
        import time

        start = time.time()
        displayed_interim_ids: set[str] = set()

        while time.time() - start < timeout:
            messages = read_last_n(self.queue_path, 10)

            for msg in messages:
                if (
                    msg.reply_to == message_id
                    and msg.to == "transport"
                    and msg.from_agent
                ):
                    if msg.intent == "interim":
                        if msg.id not in displayed_interim_ids:
                            displayed_interim_ids.add(msg.id)
                            print(f"\n[{msg.from_agent}] {msg.payload.get('text', '')}")
                    else:
                        return msg

            time.sleep(0.1)

        return None

    def display(self, msg: Message) -> None:
        """Display a message to the terminal."""
        text = msg.payload.get("text", "")

        if msg.from_agent:
            agent = msg.from_agent
            print(f"\n[{agent}] {text}")
        else:
            print(f"\n> {text}")

    def interactive(self) -> None:
        """Run interactive CLI session."""
        print("outheis CLI (type 'exit' to quit)")
        print("-" * 40)

        while True:
            try:
                text = input("\n> ").strip()

                if not text:
                    continue

                if text.lower() in ("exit", "quit", "q"):
                    break

                msg = self.send(text)
                print(f"[sent: {msg.id[:8]}...]")

                # Wait for response
                response = self.wait_for_response(msg.id)

                if response:
                    self.display(response)
                else:
                    print("[no response received]")

            except KeyboardInterrupt:
                print("\n[interrupted]")
                break
            except EOFError:
                break

        print("\nGoodbye.")
