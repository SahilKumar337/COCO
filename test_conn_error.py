import asyncio
import os
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY")

async def test_connection():
    client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            language_code="en-IN",
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        )
    )
    try:
        async with client.aio.live.connect(model="models/gemini-2.5-flash-native-audio-latest", config=config) as session:
            print("Successfully connected with en-IN")
    except Exception as e:
        print(f"FAILED with en-IN: {e}")

    # Try without language_code
    config2 = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        )
    )
    try:
        async with client.aio.live.connect(model="models/gemini-2.5-flash-native-audio-latest", config=config2) as session:
            print("Successfully connected without language_code")
    except Exception as e:
        print(f"FAILED without language_code: {e}")

asyncio.run(test_connection())
