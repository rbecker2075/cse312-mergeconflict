
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from database import users_collection, sessions_collection # Import from database.py
from typing import Optional
import os
import string # Required for checking special characters in passwords
from auth import get_password_hash, verify_password, create_access_token, hash_token, get_current_user
import uuid
from starlette.staticfiles import StaticFiles
# Import for CSRF token generation
import secrets


app = FastAPI(title='test', description='testing desc', version='1.0')


# Configure static files and templates
app.mount("/static", StaticFiles(directory="FrontEnd/static"), name="static")
templates = Jinja2Templates(directory="FrontEnd")

# Commented out direct database connection setup
# client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
# db = client.app_database
# users_collection = db.users
# sessions_collection = db.sessions


# Helper function to check password complexity requirements.
# Ensures password meets length and character type criteria.
def check_password_complexity(password: str) -> bool:
    if len(password) < 8:
        return False
    
    checks = {
        "uppercase": any(c.isupper() for c in password),
        "lowercase": any(c.islower() for c in password),
        "number": any(c.isdigit() for c in password),
        "special": any(c in string.punctuation for c in password)
    }
    
    # Check if at least three criteria are met
    met_criteria = sum(checks.values())
    
    return met_criteria >= 3


# CSRF Protection Configuration: Double Submit Cookie Pattern
CSRF_TOKEN_COOKIE_NAME = "csrftoken"
CSRF_TOKEN_FORM_NAME = "csrf_token" # Name of the hidden field in forms

# Dependency to validate the CSRF token from the cookie and form.
def validate_csrf_token(request: Request, form_token: Optional[str] = Form(None, alias=CSRF_TOKEN_FORM_NAME)):
    cookie_token = request.cookies.get(CSRF_TOKEN_COOKIE_NAME)
    if not cookie_token or not form_token or not secrets.compare_digest(cookie_token, form_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch or missing"
        )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, username: Optional[str] = Depends(get_current_user)):
    # Renders the home page, passing the current username if logged in.
    return templates.TemplateResponse("home.html", {"request": request, "username": username})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, username: Optional[str] = Depends(get_current_user)):
    # Redirects logged-in users to home page.
    if username:
        return RedirectResponse(url="/")

    # Generate a new CSRF token for the login form.
    csrf_token = secrets.token_hex(16)
    response = templates.TemplateResponse("login.html", {
        "request": request,
        CSRF_TOKEN_FORM_NAME: csrf_token # Pass token to the template context
    })
    # Set the CSRF token in a cookie.
    # httponly=False is necessary for the double submit pattern
    # if JavaScript needs to read the token from the cookie to include it in requests.
    # However, in this form-based setup, it's submitted via a hidden field,
    # so JS access might not be strictly needed unless enhancing with JS later.
    response.set_cookie(
        key=CSRF_TOKEN_COOKIE_NAME,
        value=csrf_token,
        max_age=3600, # Expires in 1 hour
        httponly=False, # Set to False for double submit cookie pattern
        samesite="Lax" # Recommended for CSRF protection
    )
    return response


@app.post("/login")
# Dependency injection for CSRF token validation.
async def login(
    request: Request,
    response: Response, # Added Response parameter to set cookies on redirect
    username: str = Form(...),
    password: str = Form(...),
    _csrf_check: None = Depends(validate_csrf_token) # Validates CSRF token
):
    # Find user and verify password.
    user = users_collection.find_one({"username": username})
    if not user or not verify_password(password, user["hashed_password"]):
        # Login failed: Regenerate CSRF token and return error page.
        csrf_token = secrets.token_hex(16)
        error_response = templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Incorrect username or password",
            CSRF_TOKEN_FORM_NAME: csrf_token # Pass new CSRF token
        }, status_code=status.HTTP_401_UNAUTHORIZED)
        # Set the new CSRF token cookie on the error response.
        error_response.set_cookie(
            key=CSRF_TOKEN_COOKIE_NAME,
            value=csrf_token,
            max_age=3600,
            httponly=False,
            samesite="Lax"
        )
        return error_response

    # Create JWT access token upon successful login.
    token = create_access_token(data={"sub": username})

    # Store a hash of the session token in the database for server-side validation.
    token_hash = hash_token(token)
    sessions_collection.insert_one({
        "username": username,
        "token_hash": token_hash
    })

    # Prepare redirect response to the home page.
    redirect_response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Set the session token as an HttpOnly cookie.
    redirect_response.set_cookie(
        key="session_token",
        value=token,
        httponly=True, # Helps mitigate XSS attacks stealing the session token
        max_age=30 * 24 * 60 * 60, # Expires in 30 days
        path="/",
        samesite="Lax" # Provides some CSRF protection for the session cookie itself
    )

    # Clear the CSRF token cookie after successful login.
    # A new token will be generated by the next GET request that renders a protected form.
    redirect_response.delete_cookie(CSRF_TOKEN_COOKIE_NAME)

    return redirect_response # Return the redirect response with cookies set.


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, username: Optional[str] = Depends(get_current_user)):
    # Redirects logged-in users to home page.
    if username:
        return RedirectResponse(url="/")

    # Generate a new CSRF token for the registration form.
    csrf_token = secrets.token_hex(16)
    response = templates.TemplateResponse("register.html", {
        "request": request,
        CSRF_TOKEN_FORM_NAME: csrf_token # Pass token to the template context
    })
    # Set the CSRF token in a cookie.
    response.set_cookie(
        key=CSRF_TOKEN_COOKIE_NAME,
        value=csrf_token,
        max_age=3600, # Expires in 1 hour
        httponly=False, # Set to False for double submit cookie pattern
        samesite="Lax"
    )
    return response


@app.post("/register")
# Dependency injection for CSRF token validation.
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    _csrf_check: None = Depends(validate_csrf_token) # Validates CSRF token
):
    # Validate username length.
    if len(username) > 15:
        error_message = "Username cannot be longer than 15 characters."
        # Regenerate CSRF token and return error page.
        csrf_token = secrets.token_hex(16)
        error_response = templates.TemplateResponse("register.html", {
            "request": request,
            "error": error_message,
            CSRF_TOKEN_FORM_NAME: csrf_token
        }, status_code=status.HTTP_400_BAD_REQUEST)
        error_response.set_cookie(
            key=CSRF_TOKEN_COOKIE_NAME,
            value=csrf_token,
            max_age=3600,
            httponly=False,
            samesite="Lax"
        )
        return error_response

    # Validate password complexity.
    if not check_password_complexity(password):
        error_message = (
            "Password must be at least 8 characters long and include at least "
            "three of the following: uppercase letters, lowercase letters, "
            "numbers, special characters."
        )
        # Regenerate CSRF token and return error page.
        csrf_token = secrets.token_hex(16)
        error_response = templates.TemplateResponse("register.html", {
            "request": request,
            "error": error_message,
            CSRF_TOKEN_FORM_NAME: csrf_token
        }, status_code=status.HTTP_400_BAD_REQUEST)
        error_response.set_cookie(
            key=CSRF_TOKEN_COOKIE_NAME,
            value=csrf_token,
            max_age=3600,
            httponly=False,
            samesite="Lax"
        )
        return error_response

    # Check if username already exists in the database.
    if users_collection.find_one({"username": username}):
        # Regenerate CSRF token and return error page.
        csrf_token = secrets.token_hex(16)
        error_response = templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Username already registered",
            CSRF_TOKEN_FORM_NAME: csrf_token
        }, status_code=status.HTTP_400_BAD_REQUEST)
        error_response.set_cookie(
            key=CSRF_TOKEN_COOKIE_NAME,
            value=csrf_token,
            max_age=3600,
            httponly=False,
            samesite="Lax"
        )
        return error_response

    # Hash the user's password securely.
    hashed_password = get_password_hash(password)

    # Store the new user in the database.
    users_collection.insert_one({
        "username": username,
        "hashed_password": hashed_password
    })

    # Redirect to the login page after successful registration.
    # Clear the CSRF token; the login page GET request will set a new one.
    redirect_response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect_response.delete_cookie(CSRF_TOKEN_COOKIE_NAME)
    return redirect_response


@app.get("/logout")
# Note: Using GET for logout can be vulnerable to CSRF if not handled carefully.
# Changing logout to a POST request with CSRF protection is generally recommended
# for actions that change state (like logging out).
async def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token:
        # Find the corresponding session hash in the database and remove it.
        token_hash = hash_token(session_token)
        sessions_collection.delete_one({"token_hash": token_hash})

    # Clear the user's session cookie.
    response.delete_cookie(key="session_token", path="/")

    # Clear the CSRF token cookie as well.
    response.delete_cookie(CSRF_TOKEN_COOKIE_NAME)

    # Redirect the user to the home page.
    return RedirectResponse(url="/")


@app.get('/login')  # Ensure this route is correctly defined with a leading slash
async def login(response: Response, request: Request):
    return FileResponse(INDEX_FILE_PATH)

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

