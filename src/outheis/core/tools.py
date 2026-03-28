"""
Shared tool schema definitions.

Each function returns a tool dict ready for the Anthropic tools parameter.
Agents import from here instead of defining schemas inline.
"""


def tool_read_file(
    description: str = "Read file detail (you have names from index)",
    path_description: str = "Filename from index",
) -> dict:
    """Read a file by path. Override description/path_description for agent-specific hints."""
    return {
        "name": "read_file",
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": path_description}
            },
            "required": ["path"],
        },
    }


def tool_write_file_path() -> dict:
    """Write or create a vault file, addressed by free path (data agent)."""
    return {
        "name": "write_file",
        "description": "Write or create file in vault",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Filename"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
    }


def tool_append_file_path() -> dict:
    """Append to a vault file, addressed by free path (data agent)."""
    return {
        "name": "append_file",
        "description": "Append content to existing file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Filename"},
                "content": {"type": "string", "description": "Content to append"},
            },
            "required": ["path", "content"],
        },
    }


def tool_write_file_name(allowed: list[str]) -> dict:
    """Write/replace a named agenda file, restricted to *allowed* names."""
    return {
        "name": "write_file",
        "description": "Write/replace a file (agenda, daily, exchange, or shadow)",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "enum": allowed},
                "content": {"type": "string", "description": "Full content for the file"},
            },
            "required": ["file", "content"],
        },
    }


def tool_append_file_name(allowed: list[str]) -> dict:
    """Append to a named agenda file, restricted to *allowed* names."""
    return {
        "name": "append_file",
        "description": "Append content to a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "enum": allowed},
                "content": {"type": "string", "description": "Content to append"},
            },
            "required": ["file", "content"],
        },
    }


def tool_error(message: str) -> str:
    """Standard tool error string returned to the LLM."""
    return f"Error: {message}"


def tool_load_skill(
    description: str = "Load detailed skill instructions",
    topic_description: str = "Topic",
) -> dict:
    """Load skill instructions. Override description/topic_description per agent."""
    return {
        "name": "load_skill",
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": topic_description}
            },
            "required": ["topic"],
        },
    }
