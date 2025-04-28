from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import secrets
import hashlib
import os
from database import sessions_collection # Import database collection for session validation

# Security Configuration
# Use environment variable for SECRET_KEY in production
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256" # Algorithm for JWT encoding
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # Token validity: 30 days

# Password Hashing Context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pydantic model for user data (example, not directly used in this file)
class User(BaseModel):
    username: str
    salt: str
    hashed_password: str

# Pydantic model for data expected within JWT payload
class TokenData(BaseModel):
    username: Optional[str] = None

# Verifies a plain text password against a stored hash.
def verify_password(plain_password: str, salt: str, hashed_password: str) -> bool:
    """Verify a password by prepending the salt and matching against the stored hash."""
    return pwd_context.verify(salt + plain_password, hashed_password)

# Hashes a plain text password using the configured context.
def get_password_hash(password: str) -> tuple[str, str]:
    """Generate a unique salt and hash the password with it, returning (salt, hashed_password)."""
    salt = secrets.token_hex(16)
    hashed = pwd_context.hash(salt + password)
    return salt, hashed

# Creates a JWT access token.
def create_access_token(data: dict):
    to_encode = data.copy()
    # Set token expiration time
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    # Encode the payload into a JWT string
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Creates a SHA256 hash of a token for secure storage.
def hash_token(token: str) -> str:
    """Create a hash of the token to store in the database"""
    return hashlib.sha256(token.encode()).hexdigest()

# Verifies if a given token matches a stored hash.
def verify_token_hash(token: str, stored_hash: str) -> bool:
    """Verify if a token matches the stored hash"""
    return hash_token(token) == stored_hash

# Dependency function to get the current user based on the session token cookie.
async def get_current_user(session_token: Optional[str] = Cookie(None)):
    # If no session token cookie is present, user is not logged in.
    if not session_token:
        return None

    # Hash the token received from the cookie for database lookup.
    token_hash = hash_token(session_token)

    # Check if a session with this token hash exists in the database.
    session = sessions_collection.find_one({"token_hash": token_hash})
    if not session:
        # Session doesn't exist or was invalidated (e.g., logout).
        return None # Session not found in DB

    try:
        # Decode the JWT token to extract the payload.
        payload = jwt.decode(session_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub") # 'sub' (subject) usually holds the username
        if username is None:
            # Token payload is missing the username.
            return None # Username not in token payload

        # Optional security check: Verify username in token matches the one stored with the hash.
        # This helps detect if a token for one user is somehow associated with another user's session hash.
        if username != session.get("username"):
             return None # Mismatch, potentially indicating tampering

        # Create TokenData model with the validated username.
        token_data = TokenData(username=username)
    except JWTError:
        # Token is invalid (e.g., expired, signature mismatch, malformed).
        return None # Token is invalid (expired, wrong signature, etc.)

    # Return the username if token and session are valid.
    return token_data.username 