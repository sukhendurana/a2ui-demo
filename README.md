# Preferred-name A2UI + FastMCP demo

This is a small, local demo of a safe update flow:

```text
Browser chat
  -> local web bridge (FastAPI)
  -> FastMCP tool call
  -> Spring PUT /profile/preferred-name?preferredName=...
```

The browser never calls the Spring API directly. It gets an A2UI confirmation card first; only **Confirm** calls the `a2ui_action` MCP tool, which performs the Spring PUT.

## What you need

- Python 3.10+
- Your Spring app listening at `http://127.0.0.1:8080`
- A terminal in this directory

## 1. Install the demo dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Start Spring

Start your existing Spring app. Its endpoint must accept:

```text
PUT http://127.0.0.1:8080/profile/preferred-name?preferredName=Ada%20Lovelace
```

If it uses another host or port, set `SPRING_API_URL` before starting the MCP server:

```bash
export SPRING_API_URL="http://127.0.0.1:8080/profile/preferred-name"
```

## 3. Start the FastMCP server

In terminal 1:

```bash
source .venv/bin/activate
fastmcp run mcp_server.py --transport http --host 127.0.0.1 --port 8001
```

Its MCP endpoint is `http://127.0.0.1:8001/mcp`.

## 4. Start the browser client

In terminal 2:

```bash
source .venv/bin/activate
uvicorn web_client:app --reload --host 127.0.0.1 --port 5173
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173), then type:

```text
Update my preferred name to Ada Lovelace
```

The expected sequence is:

1. The browser posts the chat message to the web bridge.
2. The web bridge calls `propose_preferred_name` over MCP.
3. The MCP server returns A2UI `updateDataModel` data and links it to the A2UI resource.
4. The web bridge obtains the A2UI resource (the static card template) over MCP, then the browser renders it in chat.
5. **Confirm** sends the five-field A2UI action envelope to the web bridge.
6. The web bridge calls `a2ui_action` over MCP.
7. `a2ui_action` calls your Spring PUT endpoint and deletes the A2UI confirmation surface on success.

## Why this is A2UI-over-MCP

- `a2ui://preferred-name-confirmation` is an MCP resource with MIME type `application/a2ui+json`.
- `propose_preferred_name` supplies dynamic values as an A2UI `updateDataModel` event inside an MCP `EmbeddedResource`.
- Tool metadata and the dynamic result both link to the static presentation resource with `ui.resourceUri`.
- The confirm/cancel buttons carry A2UI actions; the browser sends the standard `name`, `surfaceId`, `sourceComponentId`, `timestamp`, and `context` fields to the `a2ui_action` MCP tool.

This follows the A2UI MCP pattern of a cacheable presentation resource plus dynamic tool data. The demo renderer deliberately supports only the Basic Catalog components it needs: `Card`, `Column`, `Row`, `Text`, and `Button`.

## Important demo limitations

- Natural-language recognition is intentionally a small regex parser, not an LLM. It accepts messages such as “Update my preferred name to Ada.” Add an LLM only after the confirmation/update path works.
- Pending confirmations are in memory. In a real application, tie them to an authenticated user and store them in a database/Redis with an expiry.
- Add authentication and authorization to both the browser bridge and your Spring API before exposing this beyond localhost.
- The browser bridge does not trust the name coming back from the confirmation component; it uses its server-side pending confirmation record instead.

## Do you need a skill file?

No. A `SKILL.md` is only a reusable instruction package for an AI coding agent. It is not part of A2UI, FastMCP, the browser client, or the Spring app. It becomes useful only if you want an agent to repeatedly follow organization-specific rules while creating or changing MCP tools.
