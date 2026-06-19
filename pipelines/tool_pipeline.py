"""
pipelines/tool_pipeline.py — WALL-E AI Tool Registry
Registry-based tool dispatcher. Adding a new tool = one decorated function.
No more giant if/elif dispatch chains in session code.

To add a new tool:
  1. Define a function below
  2. Decorate with @tool_registry.register("tool_name", description="...", parameters={...})
  3. Declare it in GeminiPipeline._live_config() — that's it.

Created by K.Astra and its members.
"""

import re
import os
import subprocess
import time
import json
import webbrowser
import urllib.parse
from typing import Callable, Any

from google.genai import types

from core.logger import get_logger

log = get_logger("pipeline.tools")


class ToolRegistry:
    """
    Central registry mapping tool names → callable functions.
    Provides deduplication (3-second window) to prevent double-execution
    when Gemini re-sends a tool call on session jitter.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}   # name → {fn, declaration}
        self._cache: dict[str, float] = {}  # call_key → last_executed_ts

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        required: list[str] | None = None,
    ) -> Callable:
        """Decorator factory. Registers a function as a Gemini-callable tool."""
        def decorator(fn: Callable) -> Callable:
            self._tools[name] = {
                "fn": fn,
                "declaration": types.FunctionDeclaration(
                    name=name,
                    description=description,
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            k: types.Schema(type=v["type"].upper(), description=v.get("description", ""))
                            for k, v in parameters.items()
                        },
                        required=required or list(parameters.keys()),
                    ),
                ),
            }
            log.debug(f"Registered tool: {name}")
            return fn
        return decorator

    @property
    def declarations(self) -> list[types.FunctionDeclaration]:
        """Return all registered FunctionDeclarations for Gemini config."""
        return [v["declaration"] for v in self._tools.values()]

    def dispatch(self, tool_call) -> list[types.FunctionResponse]:
        """
        Execute all function calls in a Gemini tool_call response.
        Applies 3-second deduplication guard per unique (name, args) pair.
        """
        responses = []
        for fc in tool_call.function_calls:
            name = fc.name
            args = fc.args

            # Deduplication guard
            call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
            now = time.time()
            if now - self._cache.get(call_key, 0) < 3.0:
                log.debug(f"🛡 Deduplicated redundant call: {name}")
                responses.append(types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={"result": "Action already in progress or completed."},
                ))
                continue

            self._cache[call_key] = now
            tool = self._tools.get(name)

            if not tool:
                log.warning(f"Unknown tool called: {name}")
                result = f"Error: Unknown tool '{name}'"
            else:
                try:
                    log.info(f"Executing tool '{name}' with args: {args}")
                    result = tool["fn"](**args)
                except Exception as e:
                    log.error(f"Tool '{name}' raised: {e}")
                    result = f"Error executing '{name}': {e}"

            responses.append(types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": result},
            ))
        return responses


# ── Singleton registry ─────────────────────────────────────────────────────────
tool_registry = ToolRegistry()

# ── Tool definitions ──────────────────────────────────────────────────────────

_SILENT_SUFFIX = (
    " INSTRUCTION: The action is complete. "
    "Do NOT confirm verbally. End your turn silently."
)


@tool_registry.register(
    "open_url",
    description="Opens a specific website URL in the user's default browser.",
    parameters={"url": {"type": "string", "description": "The full URL to open (must start with http:// or https://)"}},
)
def open_url(url: str) -> str:
    """Security-checked URL opener."""
    if not url.startswith(("http://", "https://")):
        return f"Error: Blocked unsafe URL scheme: {url}"
    try:
        # webbrowser.open() is the correct cross-platform API for URLs.
        # os.startfile() is for local files, not URLs, and is unreliable for http.
        webbrowser.open(url)
    except Exception as e:
        return f"Error opening URL: {e}"
    return f"Opened {url}." + _SILENT_SUFFIX


@tool_registry.register(
    "play_music_on_youtube",
    description="Plays a song, artist, or video on YouTube. Use when the user asks to play music or a specific video.",
    parameters={"query": {"type": "string", "description": "Search query for the song, artist, or video"}},
)
def play_music_on_youtube(query: str) -> str:
    """Plays music on YouTube via DuckDuckGo !ducky redirect."""
    encoded = urllib.parse.quote(query)
    url = f"https://duckduckgo.com/?q=!ducky+site%3Ayoutube.com+{encoded}"
    try:
        os.startfile(url)
    except Exception:
        webbrowser.open(url)
    return f"Playing '{query}' on YouTube." + _SILENT_SUFFIX


@tool_registry.register(
    "open_application",
    description="Opens a local application on the user's Windows PC (e.g. notepad, calculator, chrome, vscode).",
    parameters={"app_name": {"type": "string", "description": "Name of the application to open"}},
)
def open_application(app_name: str) -> str:
    """Opens a Windows application by name with a curated alias map."""
    APPS = {
        "calculator":    "calc.exe",
        "notepad":       "notepad.exe",
        "paint":         "mspaint.exe",
        "explorer":      "explorer.exe",
        "cmd":           "cmd.exe",
        "chrome":        "chrome.exe",
        "edge":          "msedge.exe",
        "vscode":        "code",
        "word":          "winword.exe",
        "excel":         "excel.exe",
        "powerpoint":    "powerpnt.exe",
        "ppt":           "powerpnt.exe",
        "spotify":       "spotify.exe",
        "control panel": "control",
        "settings":      "ms-settings:",
        "task manager":  "taskmgr",
    }
    cmd = APPS.get(app_name.lower().strip(), app_name.lower().strip())

    # Security: block shell injection characters but allow colons and slashes
    # that appear in valid Windows paths like ms-settings: or C:/path/to/app
    if not re.match(r"^[a-zA-Z0-9_.\-\s:/\\]+$", cmd):
        return f"Error: Invalid application command '{cmd}'."

    try:
        if cmd.endswith(":") or cmd.startswith("ms-"):
            # Use os.startfile for URI protocol handlers (ms-settings:, etc.)
            os.startfile(cmd)
        else:
            subprocess.Popen(f"start {cmd}", shell=True)
        return f"Opened {app_name}." + _SILENT_SUFFIX
    except Exception as e:
        return f"Error opening '{app_name}': {e}"


# ── Live Web Search ────────────────────────────────────────────────────────────

@tool_registry.register(
    "web_search",
    description=(
        "Search the web for real-time information: current news, weather, sports scores, "
        "stock prices, events, or any information that may have changed recently. "
        "Use this whenever the user asks about anything time-sensitive or current."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "The search query. Be specific and concise for best results.",
        },
        "max_results": {
            "type": "string",
            "description": "Number of results to fetch. Use '4' for most queries, '8' for research-heavy queries.",
        },
    },
    required=["query"],
)
def web_search(query: str, max_results: str = "5") -> str:
    """Search the web via DuckDuckGo and return summarised results."""
    try:
        from duckduckgo_search import DDGS
        n = max(1, min(int(max_results), 10))
        results = []
        with DDGS() as ddgs_client:
            for r in ddgs_client.text(query, max_results=n):
                title = r.get("title", "")
                body  = r.get("body", "")
                href  = r.get("href", "")
                results.append(f"• {title}\n  {body}\n  Source: {href}")

        if not results:
            return f"No results found for: {query}"

        summary = "\n\n".join(results)
        log.info(f"web_search: '{query}' → {len(results)} results")
        return f"Search results for '{query}':\n\n{summary}"

    except Exception as e:
        log.error(f"web_search error: {e}")
        return f"Search failed: {e}. Please try again or answer from your knowledge."


# ── User Location ──────────────────────────────────────────────────────────────
# The browser sends the user's location over WebSocket when geolocation is available.
# server.py stores it in _SESSION_LOCATION. This tool reads it for WALL-E.

_SESSION_LOCATION: dict | None = None


def update_session_location(location: dict) -> None:
    """Called by server.py when the browser sends a location update."""
    global _SESSION_LOCATION
    _SESSION_LOCATION = location
    log.info(
        f"Location updated: {location.get('city', '?')}, "
        f"{location.get('country', '?')} "
        f"({location.get('lat', '?')}, {location.get('lon', '?')})"
    )


@tool_registry.register(
    "get_user_location",
    description=(
        "Get the user's current real-time location (city, country, coordinates). "
        "Use when the user asks about their location, nearby places, local weather, "
        "or anything that requires knowing where they are."
    ),
    parameters={
        "detail_level": {
            "type": "string",
            "description": "Level of detail: 'full' for all info, 'city' for city only. Default: 'full'",
        }
    },
    required=[],
)
def get_user_location(detail_level: str = "full") -> str:
    """Returns the current location sent by the user's browser."""
    if not _SESSION_LOCATION:
        return (
            "Location not available. The user may not have granted location permission "
            "in their browser, or location has not been shared yet."
        )
    loc = _SESSION_LOCATION
    parts = []
    if loc.get("city"):       parts.append(f"City: {loc['city']}")
    if loc.get("state"):      parts.append(f"State/Region: {loc['state']}")
    if loc.get("country"):    parts.append(f"Country: {loc['country']}")
    if loc.get("lat"):        parts.append(f"Coordinates: {loc['lat']}, {loc['lon']}")
    if loc.get("timezone"):   parts.append(f"Timezone: {loc['timezone']}")
    if loc.get("accuracy_m"): parts.append(f"GPS Accuracy: ±{loc['accuracy_m']}m")
    return "\n".join(parts) if parts else "Location data is incomplete."
