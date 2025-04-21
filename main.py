import uvicorn # Added for running the app if needed
from fastapi import FastAPI, Request, Depends, HTTPException, status, Response, Cookie, Body
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse # Added JSONResponse
from fastapi.staticfiles import StaticFiles
from database import users_collection, sessions_collection # Import from database.py
from typing import Optional
import os
import string # Required for checking special characters in passwords
from auth import get_password_hash, verify_password, create_access_token, hash_token, get_current_user
from pydantic import BaseModel # Added for request bodies

app = FastAPI(title='Merge Conflict Game', description='Authentication and Game API', version='1.0')

# Configure static files
# Mount 'public/imgs' directory to serve images under '/imgs' path
app.mount("/imgs", StaticFiles(directory="public/imgs"), name="imgs")
# Removed old '/static' mount and Jinja2Templates setup

# --- Pydantic Models for Request Bodies ---
class UserCredentials(BaseModel):
    username: str
    password: str

# --- Helper function (keep as is) ---
def check_password_complexity(password: str) -> bool:
    if len(password) < 8:
        return False
    checks = {
        "uppercase": any(c.isupper() for c in password),
        "lowercase": any(c.islower() for c in password),
        "number": any(c.isdigit() for c in password),
        "special": any(c in string.punctuation for c in password)
    }
    met_criteria = sum(checks.values())
    return met_criteria >= 3

# --- Removed CSRF Configuration and Validation ---

# --- Routes for Serving Frontend Pages ---

@app.get("/", response_class=FileResponse)
async def serve_home_page():
    # Serve the main index page
    # Check if file exists? Add error handling if needed.
    return FileResponse("public/index.html")

@app.get("/login", response_class=FileResponse)
async def serve_login_page(username: Optional[str] = Depends(get_current_user)):
    # Redirect if already logged in
    if username:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse("public/login_page.html")

@app.get("/register", response_class=FileResponse)
async def serve_register_page(username: Optional[str] = Depends(get_current_user)):
    # Redirect if already logged in
    if username:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse("public/register.html")


# --- Authentication API Endpoints ---

@app.get("/auth/status")
async def auth_status(username: Optional[str] = Depends(get_current_user)):
    """Checks if the user is currently logged in based on session cookie."""
    if username:
        return {"logged_in": True, "username": username}
    else:
        return {"logged_in": False}

@app.post("/api/login")
async def api_login(credentials: UserCredentials = Body(...), response: Response = Response()):
    """Handles user login via API, expects JSON credentials."""
    user = users_collection.find_one({"username": credentials.username})
    if not user or not verify_password(credentials.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Create JWT access token upon successful login.
    token = create_access_token(data={"sub": credentials.username})

    # Store a hash of the session token in the database.
    token_hash = hash_token(token)
    # Use update_one with upsert=True to avoid duplicate sessions if user logs in again
    sessions_collection.update_one(
        {"username": credentials.username},
        {"$set": {"token_hash": token_hash}},
        upsert=True
    )

    # Set the session token as an HttpOnly cookie on the provided Response object.
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=30 * 24 * 60 * 60, # 30 days
        path="/",
        samesite="Lax",
        secure=False, # Set to True if using HTTPS
        domain=None, # Adjust if needed
    )
    # Return success status. Frontend JS will handle redirect.
    # Need to explicitly return the response object for the cookie to be set.
    return JSONResponse(content={"message": "Login successful"}, status_code=status.HTTP_200_OK, headers=response.headers)


@app.post("/api/register")
async def api_register(credentials: UserCredentials = Body(...)):
    """Handles user registration via API, expects JSON credentials."""
    # Validate username length.
    if len(credentials.username) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username cannot be longer than 15 characters."
        )

    # Validate password complexity.
    if not check_password_complexity(credentials.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long and include at least three of: uppercase, lowercase, number, special character."
        )

    # Check if username already exists.
    if users_collection.find_one({"username": credentials.username}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, # Use 409 Conflict for existing resource
            detail="Username already registered"
        )

    # Hash the password.
    hashed_password = get_password_hash(credentials.password)

    # Store the new user.
    users_collection.insert_one({
        "username": credentials.username,
        "hashed_password": hashed_password
    })

    # Return success status. Frontend JS will handle redirect to login.
    return JSONResponse(content={"message": "Registration successful"}, status_code=status.HTTP_201_CREATED)


@app.get("/logout")
async def logout(response: Response = Response(), session_token: Optional[str] = Cookie(None)):
    """Logs the user out by deleting the session and clearing the cookie."""
    if session_token:
        token_hash = hash_token(session_token)
        sessions_collection.delete_one({"token_hash": token_hash})

    # Create a redirect response AFTER deleting the cookie info from the passed 'response'.
    redirect_response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    # Clear the session token cookie.
    redirect_response.delete_cookie(key="session_token", path="/") # Apply delete_cookie to the redirect response

    # Removed CSRF cookie deletion

    return redirect_response # Return the redirect response

# --- Remove duplicate /login route and /hello/{name} ---

# --- Add main execution block (optional, for running directly) ---
# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8000)

