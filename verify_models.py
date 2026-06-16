"""
verify_models.py — SIFRA AI Diagnostic Tool
Automatically tests which Gemini models are available for your API key.
"""

import os
import asyncio
from google import genai
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

MODELS_TO_TEST = [
    "models/gemini-2.0-flash-exp",
    "models/gemini-2.0-flash-live-preview-02-05",
    "models/gemini-2.5-flash-native-audio-latest",
]

async def test_model(client, model_name):
    print(f"Testing {model_name}...")
    try:
        # We try a simple non-streaming call first to check availability
        response = client.models.generate_content(
            model=model_name,
            contents="Hello, are you available?"
        )
        print(f"  \u2705 {model_name} is AVAILABLE (Standard API)")
        
        # Now check if it supports Live Bidi
        print(f"  Checking Live support for {model_name}...")
        try:
            # We just try to open the connection and close it immediately
            async with client.aio.live.connect(model=model_name, config={"response_modalities": ["AUDIO"]}) as session:
                print(f"  \ud83c\udfa4 {model_name} supports LIVE BIDIRECTIONAL AUDIO!")
        except Exception as e:
            print(f"  \u274c {model_name} does NOT support Live API in your region yet: {e}")
            
    except Exception as e:
        print(f"  \u274c {model_name} is NOT FOUND or NOT AUTHORIZED: {e}")
    print("-" * 50)

async def main():
    if not API_KEY:
        print("\u274c Error: No API key found in .env (GEMINI_API_KEY or GOOGLE_API_KEY)")
        return

    client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1beta"})
    
    print("=" * 50)
    print(" SIFRA AI - Automatic Model Testing ")
    print("=" * 50)
    
    for model in MODELS_TO_TEST:
        await test_model(client, model)

if __name__ == "__main__":
    asyncio.run(main())
