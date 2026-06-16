import os
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
import bcrypt
import jwt
import httpx

import database

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Security configuration
SECRET_KEY = os.environ.get("JWT_SECRET", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Google OAuth Config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
# This should match exactly what is configured in Google Cloud Console
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")

def verify_password(plain_password, hashed_password):
    if not hashed_password: return False
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user_id(request: Request) -> Optional[int]:
    token = request.cookies.get("sifra_session")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return int(user_id)
    except jwt.PyJWTError:
        return None

# ── Endpoints ─────────────────────────────────────────────────────────────

from pydantic import BaseModel
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/signup")
async def signup(body: SignupRequest, response: Response):
    user = database.get_user_by_email(body.email)
    if user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(body.password)
    
    user_id = database.create_user(
        email=body.email, 
        name=body.name, 
        password_hash=hashed_password
    )
    
    token = create_access_token({"sub": str(user_id)})
    response.set_cookie(key="sifra_session", value=token, httponly=True, max_age=86400*30, samesite="lax")
    return {"status": "success", "user_id": user_id}

@router.post("/login")
async def login(body: LoginRequest, response: Response):
    user = database.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_access_token({"sub": str(user["id"])})
    response.set_cookie(key="sifra_session", value=token, httponly=True, max_age=86400*30, samesite="lax")
    return {"status": "success", "user_id": user["id"], "name": user["name"]}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="sifra_session")
    return {"status": "success"}

@router.get("/me")
async def get_me(request: Request):
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "ai_voice": user["ai_voice"],
        "ai_persona": user["ai_persona"]
    }

# ── Google OAuth ─────────────────────────────────────────────────────────

@router.get("/google/login")
async def google_login():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google Auth is not configured on this server.")
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        "&access_type=offline"
    )
    return RedirectResponse(auth_url)

@router.get("/google/callback")
async def google_callback(code: str, response: Response):
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not provided")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    
    async with httpx.AsyncClient() as client:
        token_res = await client.post(token_url, data=data)
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange token with Google")
            
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        
        # Get user info
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        userinfo_res = await client.get(userinfo_url, headers=headers)
        
        if userinfo_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info from Google")
            
        user_info = userinfo_res.json()
        email = user_info.get("email")
        name = user_info.get("name")
        google_id = user_info.get("id")
        
        user = database.get_user_by_email(email)
        if not user:
            # Create user — no admin promotion
            user_id = database.create_user(
                email=email,
                name=name,
                google_id=google_id
            )
        else:
            user_id = user["id"]
            
        # Log them in
        token = create_access_token({"sub": str(user_id)})
        
        # We must return a RedirectResponse that also sets the cookie
        redirect = RedirectResponse(url="/")
        redirect.set_cookie(key="sifra_session", value=token, httponly=True, max_age=86400*30, samesite="lax")
        return redirect

# ── Settings ─────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    ai_voice: str
    ai_persona: str

@router.post("/settings")
async def update_settings(body: SettingsUpdate, request: Request):
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    database.update_user_settings(user_id, body.ai_voice, body.ai_persona)
    return {"status": "success"}
