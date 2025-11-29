
import os, json, datetime, requests
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

# Load .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://mailbot:mailbotpass@localhost:5432/mailbotdb")

# Handle Render's DATABASE_URL format (postgres:// -> postgresql://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
FERNET_KEY = os.environ.get("FERNET_KEY")
if not FERNET_KEY:
    raise RuntimeError("Set FERNET_KEY env var")

fernet = Fernet(FERNET_KEY.encode())

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()

class UserToken(Base):
    __tablename__ = "user_tokens"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(256), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=True)
    encrypted_payload = Column(Text, nullable=False)
    scopes = Column(String(512), nullable=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class UserPrompt(Base):
    __tablename__ = "user_prompts"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(256), nullable=False, index=True)
    prompt_type = Column(String(64), nullable=False)  # "classify", "summarize", "draft", "ask"
    custom_prompt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


def encrypt_payload(payload: dict) -> str:
    raw = json.dumps(payload).encode("utf-8")
    token = fernet.encrypt(raw)
    return token.decode("utf-8")

def decrypt_payload(ciphertext: str) -> dict:
    try:
        raw = fernet.decrypt(ciphertext.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except InvalidToken:
        raise RuntimeError("Invalid FERNET_KEY or corrupted token payload")

def save_user_token(email: str, name: str, token_payload: dict, scopes: str = None):
    session = SessionLocal()
    try:
        enc = encrypt_payload(token_payload)
        existing = session.query(UserToken).filter_by(email=email).first()
        if existing:
            existing.encrypted_payload = enc
            existing.name = name
            existing.scopes = scopes
        else:
            new = UserToken(email=email, name=name, encrypted_payload=enc, scopes=scopes)
            session.add(new)
        session.commit()
    finally:
        session.close()

def get_user_token(email: str):
    session = SessionLocal()
    try:
        obj = session.query(UserToken).filter_by(email=email).first()
        if not obj:
            return None
        payload = decrypt_payload(obj.encrypted_payload)
        return {"email": obj.email, "name": obj.name, "scopes": obj.scopes, "payload": payload}
    finally:
        session.close()

def delete_user_token(email: str):
    session = SessionLocal()
    try:
        obj = session.query(UserToken).filter_by(email=email).first()
        if obj:
            session.delete(obj)
            session.commit()
    finally:
        session.close()

def get_user_prompt(email: str, prompt_type: str):
    """Get custom prompt for a user; returns None if not found"""
    session = SessionLocal()
    try:
        obj = session.query(UserPrompt).filter_by(email=email, prompt_type=prompt_type).first()
        if not obj:
            return None
        return {"email": obj.email, "prompt_type": obj.prompt_type, "custom_prompt": obj.custom_prompt}
    finally:
        session.close()

def save_user_prompt(email: str, prompt_type: str, custom_prompt: str):
    """Save or update custom prompt for a user"""
    session = SessionLocal()
    try:
        existing = session.query(UserPrompt).filter_by(email=email, prompt_type=prompt_type).first()
        if existing:
            existing.custom_prompt = custom_prompt
        else:
            new = UserPrompt(email=email, prompt_type=prompt_type, custom_prompt=custom_prompt)
            session.add(new)
        session.commit()
    finally:
        session.close()

def get_all_user_prompts(email: str):
    """Get all custom prompts for a user"""
    session = SessionLocal()
    try:
        objs = session.query(UserPrompt).filter_by(email=email).all()
        return [{"email": obj.email, "prompt_type": obj.prompt_type, "custom_prompt": obj.custom_prompt} for obj in objs]
    finally:
        session.close()

# Token refresh helper
def refresh_access_token(email: str):
    rec = get_user_token(email)
    if not rec:
        raise RuntimeError("no tokens")
    payload = rec["payload"]
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("no refresh token")
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    r = requests.post(token_url, data=data, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"refresh failed: {r.status_code} {r.text}")
    new = r.json()
    # preserve refresh_token if not returned
    if "refresh_token" not in new:
        new["refresh_token"] = refresh_token
    new["obtained_at"] = datetime.datetime.utcnow().isoformat()
    save_user_token(email, rec["name"], new, scopes=new.get("scope"))
    return new
