"""FastMCP server that returns an A2UI confirmation before updating Spring."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import EmbeddedResource, TextContent, TextResourceContents


SPRING_API_URL = os.getenv(
    "SPRING_API_URL", "http://127.0.0.1:8080/profile/preferred-name"
)
A2UI_MIME_TYPE = "application/a2ui+json"
A2UI_RESOURCE_URI = "a2ui://preferred-name-confirmation"
A2UI_SURFACE_ID = "preferred-name-confirmation"
A2UI_UI_META = {
    "ui": {"resourceUri": A2UI_RESOURCE_URI, "mimeType": A2UI_MIME_TYPE}
}

mcp = FastMCP("Preferred Name A2UI Server")


def confirmation_template() -> list[dict[str, Any]]:
    """The static A2UI presentation resource, using the v0.9 Basic Catalog."""
    return [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": A2UI_SURFACE_ID,
                "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json",
            },
        },
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": A2UI_SURFACE_ID,
                "components": [
                    {"id": "root", "component": "Card", "child": "content"},
                    {
                        "id": "content",
                        "component": "Column",
                        "children": ["title", "message", "actions"],
                    },
                    {
                        "id": "title",
                        "component": "Text",
                        "variant": "h3",
                        "text": {"path": "/title"},
                    },
                    {
                        "id": "message",
                        "component": "Text",
                        "text": {"path": "/message"},
                    },
                    {
                        "id": "actions",
                        "component": "Row",
                        "children": ["confirm", "cancel"],
                    },
                    {"id": "confirm-label", "component": "Text", "text": "Confirm"},
                    {
                        "id": "confirm",
                        "component": "Button",
                        "variant": "primary",
                        "child": "confirm-label",
                        "action": {
                            "event": {
                                "name": "confirm_preferred_name",
                                "context": {
                                    "confirmationId": {"path": "/confirmationId"},
                                    "preferredName": {"path": "/preferredName"},
                                },
                            }
                        },
                    },
                    {"id": "cancel-label", "component": "Text", "text": "Cancel"},
                    {
                        "id": "cancel",
                        "component": "Button",
                        "variant": "borderless",
                        "child": "cancel-label",
                        "action": {
                            "event": {
                                "name": "cancel_preferred_name",
                                "context": {
                                    "confirmationId": {"path": "/confirmationId"},
                                },
                            }
                        },
                    },
                ],
            },
        },
    ]


def a2ui_tool_result(
    summary: str, events: list[dict[str, Any]], structured_data: dict[str, Any]
) -> ToolResult:
    """Return an A2UI EmbeddedResource plus a text fallback for non-A2UI clients."""
    return ToolResult(
        content=[
            TextContent(type="text", text=summary),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=f"{A2UI_RESOURCE_URI}/data",
                    mime_type=A2UI_MIME_TYPE,
                    text=json.dumps(events),
                ),
            ),
        ],
        structured_content=structured_data,
        meta=A2UI_UI_META,
    )


async def call_spring_update(preferred_name: str) -> dict[str, Any]:
    """The only code path that contacts the Spring PUT endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.put(
                SPRING_API_URL,
                params={"preferredName": preferred_name},
            )
    except httpx.RequestError as error:
        return {
            "success": False,
            "message": f"Could not reach the Spring API: {error}",
        }

    if response.is_success:
        return {
            "success": True,
            "message": f"Preferred name updated to '{preferred_name}'.",
            "httpStatus": response.status_code,
        }

    return {
        "success": False,
        "message": f"Spring API returned HTTP {response.status_code}.",
        "httpStatus": response.status_code,
    }


@mcp.resource(A2UI_RESOURCE_URI, mime_type=A2UI_MIME_TYPE)
def preferred_name_confirmation_resource() -> list[dict[str, Any]]:
    """A static A2UI card that the client can cache and then hydrate with data."""
    return confirmation_template()


@mcp.tool(meta=A2UI_UI_META)
def propose_preferred_name(
    preferred_name: str, confirmation_id: str
) -> ToolResult:
    """Create a confirmation card. This tool never changes the Spring profile."""
    clean_name = preferred_name.strip()
    if not clean_name:
        raise ValueError("Preferred name cannot be empty.")

    data = {
        "title": "Confirm preferred name",
        "message": f"Change your preferred name to '{clean_name}'?",
        "preferredName": clean_name,
        "confirmationId": confirmation_id,
    }
    events = [
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": A2UI_SURFACE_ID,
                "path": "/",
                "value": data,
            },
        }
    ]
    return a2ui_tool_result("Waiting for confirmation.", events, data)


@mcp.tool
async def update_preferred_name(preferred_name: str) -> ToolResult:
    """Update the preferred name immediately, without an A2UI confirmation card."""
    clean_name = preferred_name.strip()
    if not clean_name:
        raise ValueError("Preferred name cannot be empty.")

    result = await call_spring_update(clean_name)
    return ToolResult(content=result["message"], structured_content=result)


@mcp.tool
async def a2ui_action(
    name: str,
    surfaceId: str,
    sourceComponentId: str,
    timestamp: str,
    context: dict[str, Any],
) -> ToolResult:
    """Handle the standard five-field A2UI action envelope from the browser renderer."""
    if surfaceId != A2UI_SURFACE_ID:
        raise ValueError("This action did not originate from the expected A2UI surface.")

    if name == "cancel_preferred_name":
        events = [{"version": "v0.9", "deleteSurface": {"surfaceId": surfaceId}}]
        return a2ui_tool_result(
            "Cancelled. No preferred name was changed.", events, {"success": True}
        )

    if name != "confirm_preferred_name":
        raise ValueError(f"Unsupported A2UI action: {name}")

    preferred_name = str(context.get("preferredName", "")).strip()
    if not preferred_name:
        raise ValueError("The confirmation action did not include a preferred name.")

    # The browser never calls Spring. It calls this MCP tool, which performs the PUT.
    result = await call_spring_update(preferred_name)
    if result["success"]:
        events = [{"version": "v0.9", "deleteSurface": {"surfaceId": surfaceId}}]
    else:
        # Keep the card visible so the user can retry after an operational failure.
        events = []
    return a2ui_tool_result(result["message"], events, result)


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)
