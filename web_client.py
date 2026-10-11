"""Same-origin browser bridge: REST for the browser, MCP for every server action."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastmcp import Client
from pydantic import BaseModel


BASE_DIR = Path(__file__).parent
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8001/mcp")
A2UI_RESOURCE_URI = "a2ui://preferred-name-confirmation"
A2UI_MIME_TYPE = "application/a2ui+json"

app = FastAPI(title="Preferred Name A2UI Chat Demo")

# Demo-only state. Replace with a server-side store keyed by the authenticated user/session.
pending_confirmations: dict[str, str] = {}
cached_confirmation_template: list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    message: str


class A2UIActionRequest(BaseModel):
    name: str
    surfaceId: str
    sourceComponentId: str
    timestamp: str
    context: dict[str, Any]


def name_from_chat_message(message: str) -> str | None:
    """A deliberately small, predictable parser for this demo; it is not an LLM."""
    patterns = [
        r"^\s*(?:please\s+)?(?:set|change|update)\s+(?:my\s+)?preferred\s+name\s+(?:to\s+)?(?P<name>.+?)\s*[.!]?\s*$",
        r"^\s*my\s+preferred\s+name\s+is\s+(?P<name>.+?)\s*[.!]?\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, message, flags=re.IGNORECASE)
        if match:
            name = match.group("name").strip(" .")
            if name:
                return name
    return None


def resource_mime_type(resource: Any) -> str | None:
    return getattr(resource, "mime_type", None) or getattr(resource, "mimeType", None)


def a2ui_events_from_tool_result(result: Any) -> list[dict[str, Any]]:
    """Extract application/a2ui+json EmbeddedResources from an MCP tool result."""
    events: list[dict[str, Any]] = []
    for block in result.content:
        resource = getattr(block, "resource", None)
        if resource and resource_mime_type(resource) == A2UI_MIME_TYPE:
            events.extend(json.loads(resource.text))
    return events


def text_from_tool_result(result: Any) -> str:
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return text
    return "The MCP server completed the request."


async def call_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    try:
        async with Client(MCP_URL) as client:
            return await client.call_tool(name, arguments)
    except Exception as error:  # This demo turns MCP transport problems into a browser-friendly error.
        raise HTTPException(status_code=502, detail=f"MCP call failed: {error}") from error


async def confirmation_template() -> list[dict[str, Any]]:
    global cached_confirmation_template
    if cached_confirmation_template is not None:
        return cached_confirmation_template

    try:
        async with Client(MCP_URL) as client:
            contents = await client.read_resource(A2UI_RESOURCE_URI)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Could not read A2UI resource: {error}") from error

    if not contents or resource_mime_type(contents[0]) != A2UI_MIME_TYPE:
        raise HTTPException(status_code=502, detail="MCP did not return the expected A2UI resource.")

    cached_confirmation_template = json.loads(contents[0].text)
    return cached_confirmation_template


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    preferred_name = name_from_chat_message(request.message)
    if not preferred_name:
        return {
            "reply": "Try: ‘Update my preferred name to Ada Lovelace’.",
            "a2ui": [],
        }

    confirmation_id = uuid4().hex
    pending_confirmations[confirmation_id] = preferred_name
    result = await call_mcp_tool(
        "propose_preferred_name",
        {"preferred_name": preferred_name, "confirmation_id": confirmation_id},
    )

    # This is the A2UI-over-MCP hydration sequence: cached resource template + tool data.
    return {
        "reply": text_from_tool_result(result),
        "a2ui": [*await confirmation_template(), *a2ui_events_from_tool_result(result)],
    }


@app.post("/api/a2ui-actions")
async def a2ui_action(action: A2UIActionRequest) -> dict[str, Any]:
    confirmation_id = str(action.context.get("confirmationId", ""))
    expected_name = pending_confirmations.get(confirmation_id)
    if not expected_name:
        raise HTTPException(status_code=400, detail="This confirmation has expired or is invalid.")

    # Do not trust the browser's name field. Use the name stored when the chat request began.
    action.context["preferredName"] = expected_name
    result = await call_mcp_tool("a2ui_action", action.model_dump())

    result_data = getattr(result, "data", None) or {}
    was_successful = bool(result_data.get("success"))
    if action.name == "cancel_preferred_name" or was_successful:
        pending_confirmations.pop(confirmation_id, None)

    # On a Spring failure the card stays rendered and the browser re-enables Confirm.
    return {
        "reply": text_from_tool_result(result),
        "a2ui": a2ui_events_from_tool_result(result),
        "retryable": action.name == "confirm_preferred_name" and not was_successful,
    }


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
