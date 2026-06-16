import httpx
import asyncio

async def test_signup():
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post("http://127.0.0.1:8001/api/auth/signup", json={
                "name": "Sahil2",
                "email": "skr246357@gmail.com",
                "password": "password123"
            })
            print(res.status_code)
            print(res.text)
        except Exception as e:
            print(e)

asyncio.run(test_signup())
