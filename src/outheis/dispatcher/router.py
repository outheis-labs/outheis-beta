"""
Dispatcher routing logic.

Routes messages to agents based on:
1. Explicit mention (@agent)
2. Fallback to Relay (which uses tools to decide)

Note: Keyword routing was removed. Relay now uses LLM tools
for intelligent routing decisions.
"""

from __future__ import annotations

import re

from outheis.core.message import AgentId, Message

# =============================================================================
# ROUTING
# =============================================================================

# Explicit mention patterns
MENTION_PATTERNS = {
    "relay": re.compile(r"@ou\b", re.IGNORECASE),
    "data": re.compile(r"@zeno\b", re.IGNORECASE),
    "agenda": re.compile(r"@cato\b", re.IGNORECASE),
    "action": re.compile(r"@hiro\b", re.IGNORECASE),
    "pattern": re.compile(r"@rumi\b", re.IGNORECASE),
    # @alan routes through relay — relay calls code agent via dispatch_sync
    # so the response always goes relay → transport, never code → transport
}


def route(msg: Message) -> AgentId | None:
    """
    Determine which agent should handle a message.

    Returns None if Relay should decide (fallback).
    """
    text = msg.payload.get("text", "").lower()

    # Check explicit mentions
    for agent, pattern in MENTION_PATTERNS.items():
        if pattern.search(text):
            return agent

    # Fallback: Relay decides via tools
    return None


# =============================================================================
# DISPATCH TARGET
# =============================================================================

def get_dispatch_target(msg: Message) -> str:
    """
    Get the final dispatch target for a message.

    Returns agent ID or "relay" as fallback.
    """
    # Messages already addressed to a specific agent
    if msg.to not in ("dispatcher", "transport"):
        return msg.to

    # Route based on content
    target = route(msg)
    return target or "relay"
