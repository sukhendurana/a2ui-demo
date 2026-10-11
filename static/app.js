const chat = document.querySelector("#chat");
const composer = document.querySelector("#composer");
const messageInput = document.querySelector("#message");
const surfaces = new Map();

function addMessage(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.textContent = text;
  chat.append(bubble);
  chat.scrollTop = chat.scrollHeight;
}

function valueAtPath(data, path) {
  if (!path || path === "/") return data;
  return path.split("/").filter(Boolean).reduce((value, key) => value?.[key], data);
}

function resolveDynamic(value, surface) {
  if (value && typeof value === "object" && "path" in value) {
    return valueAtPath(surface.data, value.path);
  }
  return value;
}

function resolveContext(context, surface) {
  return Object.fromEntries(
    Object.entries(context || {}).map(([key, value]) => [key, resolveDynamic(value, surface)]),
  );
}

function getSurfaceElement(surface) {
  let element = document.querySelector(`[data-surface-id="${surface.id}"]`);
  if (!element) {
    element = document.createElement("div");
    element.className = "a2ui-surface";
    element.dataset.surfaceId = surface.id;
    chat.append(element);
  }
  return element;
}

function renderComponent(surface, componentId) {
  const component = surface.components.get(componentId);
  if (!component) return document.createTextNode("");

  const makeChildren = (ids) => ids.map((id) => renderComponent(surface, id));
  let element;

  switch (component.component) {
    case "Card":
      element = document.createElement("section");
      element.className = "a2ui-card";
      element.append(renderComponent(surface, component.child));
      break;
    case "Column":
      element = document.createElement("div");
      element.className = "a2ui-column";
      element.append(...makeChildren(component.children || []));
      break;
    case "Row":
      element = document.createElement("div");
      element.className = "a2ui-row";
      element.append(...makeChildren(component.children || []));
      break;
    case "Text": {
      const variant = component.variant || "body";
      element = document.createElement(variant === "h3" ? "h3" : "p");
      element.textContent = String(resolveDynamic(component.text, surface) ?? "");
      break;
    }
    case "Button":
      element = document.createElement("button");
      element.type = "button";
      element.className = component.variant === "primary" ? "primary" : "secondary";
      element.append(renderComponent(surface, component.child));
      element.addEventListener("click", () => dispatchA2UIAction(surface, component, element));
      break;
    default:
      // This narrow renderer intentionally supports only the component catalog used by this demo.
      element = document.createElement("p");
      element.textContent = `Unsupported A2UI component: ${component.component}`;
  }
  return element;
}

function renderSurface(surface) {
  const host = getSurfaceElement(surface);
  host.replaceChildren(renderComponent(surface, "root"));
  chat.scrollTop = chat.scrollHeight;
}

function applyA2UI(events) {
  for (const envelope of events || []) {
    if (envelope.createSurface) {
      const { surfaceId } = envelope.createSurface;
      surfaces.set(surfaceId, { id: surfaceId, data: {}, components: new Map() });
    }

    if (envelope.updateComponents) {
      const { surfaceId, components } = envelope.updateComponents;
      const surface = surfaces.get(surfaceId);
      if (!surface) continue;
      components.forEach((component) => surface.components.set(component.id, component));
      renderSurface(surface);
    }

    if (envelope.updateDataModel) {
      const { surfaceId, path = "/", value } = envelope.updateDataModel;
      const surface = surfaces.get(surfaceId);
      if (!surface) continue;
      if (path === "/") surface.data = value || {};
      else {
        const parts = path.split("/").filter(Boolean);
        let cursor = surface.data;
        while (parts.length > 1) cursor = cursor[parts.shift()] ||= {};
        cursor[parts[0]] = value;
      }
      renderSurface(surface);
    }

    if (envelope.deleteSurface) {
      const { surfaceId } = envelope.deleteSurface;
      document.querySelector(`[data-surface-id="${surfaceId}"]`)?.remove();
      surfaces.delete(surfaceId);
    }
  }
}

async function dispatchA2UIAction(surface, component, button) {
  const event = component.action?.event;
  if (!event) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/a2ui-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: event.name,
        surfaceId: surface.id,
        sourceComponentId: component.id,
        timestamp: new Date().toISOString(),
        context: resolveContext(event.context, surface),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "The confirmation action failed.");
    applyA2UI(data.a2ui);
    addMessage("assistant", data.reply);
    if (data.retryable) button.disabled = false;
  } catch (error) {
    addMessage("assistant", `Sorry — ${error.message}`);
    button.disabled = false;
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;
  addMessage("user", message);
  messageInput.value = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "The chat request failed.");
    addMessage("assistant", data.reply);
    applyA2UI(data.a2ui);
  } catch (error) {
    addMessage("assistant", `Sorry — ${error.message}`);
  }
});
