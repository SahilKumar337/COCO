import webbrowser
import urllib.parse
import os
import subprocess
from google.genai import types

def open_url(url: str):
    """Opens a specified URL in the web browser. Use this for general web browsing."""
    # CRITICAL SECURITY FIX: Only allow safe protocols to prevent local file execution or protocol hijacking
    if not url.startswith("http://") and not url.startswith("https://"):
        return f"Error: Security violation. Blocked attempt to open unsafe URL scheme: {url}"
        
    try:
        # os.startfile is most reliable on Windows for URL protocol handling
        os.startfile(url)
    except Exception:
        webbrowser.open(url)
    return f"Successfully opened {url} in the browser. INSTRUCTION: The website is now open. You MUST NOT say anything else. Do not give a post-action summary. End your turn silently."

def play_music_on_youtube(query: str):
    """Searches and instantly plays music/videos on YouTube."""
    encoded_query = urllib.parse.quote(query)
    # Use DuckDuckGo "I'm Feeling Lucky" (!ducky) to bypass search page and directly auto-play the video
    url = f"https://duckduckgo.com/?q=!ducky+site%3Ayoutube.com+{encoded_query}"
    try:
        os.startfile(url)
    except Exception:
        webbrowser.open(url)
    return f"Successfully started playing '{query}' on YouTube. INSTRUCTION: The music is now playing. You MUST NOT say anything else. Do not give a post-action summary. End your turn silently."

def open_application(app_name: str):
    """Opens an application on the user's Windows computer."""
    apps = {
        "calculator": "calc.exe",
        "notepad": "notepad.exe",
        "paint": "mspaint.exe",
        "explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "vscode": "code",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "ppt": "powerpnt.exe",
        "power pnt": "powerpnt.exe",
        "spotify": "spotify.exe",
        "control panel": "control",
        "settings": "start ms-settings:",
        "task manager": "taskmgr",
    }
    
    app_name_lower = app_name.lower().strip()
    
    # Try to find the correct command from our map
    cmd = apps.get(app_name_lower, app_name_lower)
    
    # CRITICAL SECURITY FIX: Sanitize the final command string
    import re
    if not re.match(r"^[a-zA-Z0-9_\-\.\s:]+$", cmd):
        return f"Error: Security violation. Invalid application command '{cmd}'."
            
    try:
        # Use 'start' to let Windows handle PATH and App Paths registry keys
        subprocess.Popen(f"start {cmd}", shell=True)
        return f"Successfully opened {app_name}. INSTRUCTION: The application is now open. You MUST NOT say anything else. Do not give a post-action summary. End your turn silently."
    except Exception as e:
        return f"Error: Cannot open application '{app_name}'. {e}"

# List of tools to pass to Gemini
sifra_callable_tools = [open_url, play_music_on_youtube, open_application]

# Simple deduplication cache to prevent "double-execution" bugs
_tool_call_cache = {}

def handle_tool_call(tool_call, session):
    """Manual tool call handler for Gemini Live API."""
    import asyncio
    import time
    import json
    responses = []
    
    for fc in tool_call.function_calls:
        name = fc.name
        args = fc.args
        
        # ── DEDUPLICATION GUARD ──────────────────────────────────────────────
        # Create a unique key for this specific action (name + args)
        call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
        now = time.time()
        
        # If we ran this EXACT tool call in the last 3 seconds, skip it.
        # This prevents Gemini from repeating tasks if the session jitters.
        last_time = _tool_call_cache.get(call_key, 0)
        if now - last_time < 3.0:
            print(f"[SIFRA TOOLS] 🛡️ Deduplicated redundant call: {name}")
            # Still return a response so Gemini isn't left hanging, 
            # but don't actually perform the side effect.
            responses.append(types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": "Action already in progress or completed."}
            ))
            continue
            
        _tool_call_cache[call_key] = now
        print(f"[SIFRA TOOLS] Executing {name} with args: {args}")
        
        result = None
        if name == "open_url":
            result = open_url(**args)
        elif name == "play_music_on_youtube":
            result = play_music_on_youtube(**args)
        elif name == "open_application":
            result = open_application(**args)
        else:
            result = f"Error: Unknown tool {name}"
            
        responses.append(types.FunctionResponse(
            id=fc.id,
            name=name,
            response={"result": result}
        ))
        
    return responses
