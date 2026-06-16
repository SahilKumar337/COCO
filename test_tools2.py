import asyncio
import os
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY")

def open_browser(url: str):
    """Opens a URL in the browser. Example: open_browser('https://youtube.com/results?search_query=hello')"""
    pass

async def main():
    client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        tools=[open_browser],
    )
    async with client.aio.live.connect(model="models/gemini-2.5-flash-native-audio-latest", config=config) as session:
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text("Please open google.com using the open_browser tool.")])],
            turn_complete=True
        )
        async for response in session.receive():
            if response.tool_call:
                print("GOT TOOL CALL:", response.tool_call)
                break
            else:
                print("GOT RESPONSE")
                if response.server_content and response.server_content.turn_complete:
                    break

asyncio.run(main())
