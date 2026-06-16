import asyncio
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

async def main():
    client = genai.Client()
    async with client.aio.live.connect(model='models/gemini-2.5-flash-native-audio-latest') as session:
        print("send method:", hasattr(session, 'send'))
        print("methods:", [m for m in dir(session) if not m.startswith('_')])

asyncio.run(main())
