import uvicorn
import asyncio
import json
from fastapi import FastAPI, Request, Depends, HTTPException, status, Response, Cookie, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from database import users_collection, sessions_collection
from typing import Optional
import os
import string
from auth import get_password_hash, verify_password, create_access_token, hash_token, get_current_user
from pydantic import BaseModel # Added for request bodies
from datetime import datetime
import random
import time
import asyncio
import logging
from zoneinfo import ZoneInfo
from uuid import uuid4
from random import choice
from pathlib import Path

app = FastAPI(title='Merge Conflict Game', description='Authentication and Game API', version='1.0')

# Mount 'public/pictures' directory to serve images under '/pictures' path
app.mount("/pictures", StaticFiles(directory="public/pictures"), name="pictures")

# Mount 'game/static' directory to serve game logic 
app.mount("/game/static", StaticFiles(directory="game/static"), name="game-static")

templates = Jinja2Templates(directory="game/templates")

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


OFFSET_SECONDS = -4 * 3600

# Log to the project root (outside /logs)
def adjusted_localtime_converter(timestamp):
    """
    Applies an offset to the timestamp and then converts using time.localtime.
    """
    adjusted_timestamp = timestamp + OFFSET_SECONDS
    return time.localtime(adjusted_timestamp)

# --- Your existing setup (with modifications for the formatter) ---

# --- Basic Request Logger Setup (Existing) ---
LOG_FILE = Path("/app/host_mount/request_logs.log") # Path in container
LOG_FILE.parent.mkdir(exist_ok=True, parents=True)

# Get the specific logger instance
request_logger = logging.getLogger("request_logger")
request_logger.setLevel(logging.INFO)

# Prevent adding multiple handlers
if not request_logger.handlers:
    file_handler = logging.FileHandler(LOG_FILE)
    log_format = '%(asctime)s - %(client_ip)s - %(method)s - %(path)s'
    formatter = logging.Formatter(log_format)
    # Uncomment the next line if using the custom time converter
    # formatter.converter = adjusted_localtime_converter
    file_handler.setFormatter(formatter)
    request_logger.addHandler(file_handler)

# --- Full Request/Response Logger Setup (New) ---
FULL_LOG_FILE = Path("/app/host_mount/full_request_response.log") # Path in container
FULL_LOG_FILE.parent.mkdir(exist_ok=True, parents=True)

full_logger = logging.getLogger("full_request_response_logger")
full_logger.setLevel(logging.INFO)

# Prevent adding multiple handlers
if not full_logger.handlers:
    full_file_handler = logging.FileHandler(FULL_LOG_FILE)
    # Simple format, as details are in the message
    full_formatter = logging.Formatter('%(asctime)s - %(message)s')
    # Uncomment the next line if using the custom time converter
    # full_formatter.converter = adjusted_localtime_converter
    full_file_handler.setFormatter(full_formatter)
    full_logger.addHandler(full_file_handler)

# --- Helper Functions ---

SENSITIVE_PATHS = ["/api/login", "/api/register"]
MAX_BODY_LOG_SIZE = 2048
SESSION_TOKEN_NAME = "session_token" # Case-insensitive check later

def is_text_content_type(content_type: str | None) -> bool:
    """Check if the content type suggests text data."""
    if not content_type:
        return True # Assume text if not specified
    content_type = content_type.lower()
    return content_type.startswith(("text/", "application/json", "application/xml", "application/x-www-form-urlencoded"))

def filter_headers(headers: dict, is_response_headers: bool = False) -> dict:
    """Filters sensitive information like session tokens from headers."""
    filtered = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower == "cookie":
            # Filter session_token from Cookie header
            cookies = value.split(';')
            filtered_cookies = []
            for cookie in cookies:
                cookie_parts = cookie.strip().split('=', 1)
                if len(cookie_parts) == 2 and cookie_parts[0].strip().lower() == SESSION_TOKEN_NAME:
                    filtered_cookies.append(f"{cookie_parts[0].strip()}=[REDACTED]")
                else:
                    filtered_cookies.append(cookie.strip())
            if filtered_cookies:
                filtered[key] = '; '.join(filtered_cookies)
        elif is_response_headers and key_lower == "set-cookie":
             # Filter session_token from Set-Cookie header
            if f"{SESSION_TOKEN_NAME}=" in value.lower():
                 # Simple redaction for Set-Cookie, could be more specific
                 filtered[key] = f"{SESSION_TOKEN_NAME}=[REDACTED]; ..." # Or parse more carefully
            else:
                 filtered[key] = value
        # Add other headers to filter if needed (e.g., 'authorization')
        # elif key_lower == 'authorization':
        #     filtered[key] = "[REDACTED]"
        else:
            filtered[key] = value
    return filtered
@app.middleware("http")
async def log_requests_and_responses(request: Request, call_next):
    start_time = time.time()
    client_ip = request.headers.get("x-real-ip", request.client.host if request.client else "unknown")

    # --- Basic Request Logging (Before handling) ---
    request_logger.info("", extra={
        "client_ip": client_ip,
        "method": request.method,
        "path": request.url.path
    })

    # --- Full Request/Response Logging ---
    log_entry = []

    # 1. Log Request Line and Headers
    req_headers = dict(request.headers)
    filtered_req_headers = filter_headers(req_headers)
    log_entry.append(f"REQUEST: {request.method} {request.url.path} HTTP/{request.scope.get('http_version', '1.1')}")
    for key, value in filtered_req_headers.items():
        log_entry.append(f"{key}: {value}")
    log_entry.append("") # Blank line before body

    # 2. Log Request Body (conditionally)
    request_body = await request.body() # Read body ONCE

    # Check if path requires body redaction (login/register)
    should_redact_body = request.method == "POST" and request.url.path in SENSITIVE_PATHS

    if should_redact_body:
        log_entry.append("[Request body redacted for sensitive endpoint]")
    elif not request_body:
        log_entry.append("[No request body]")
    else:
        content_type = request.headers.get("content-type")
        if is_text_content_type(content_type):
            try:
                # Decode and truncate
                body_str = request_body.decode('utf-8', errors='replace')[:MAX_BODY_LOG_SIZE]
                log_entry.append(body_str)
                if len(request_body) > MAX_BODY_LOG_SIZE:
                    log_entry.append("... [truncated]")
            except Exception as e:
                log_entry.append(f"[Error decoding request body as text: {e}]")
        else:
            log_entry.append("[Non-text request body]")

    log_entry.append("-" * 20) # Separator

    # --- Pass request (with potentially consumed body) to the endpoint ---
    # Need to provide the body again if it was consumed. FastAPI/Starlette handles this
    # reasonably well if you await request.body() before call_next.
    # If issues arise, a more complex approach involving Request stream wrapping is needed.

    # --- Call the endpoint and get response ---
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time) # Optional: Add process time header
    except Exception as e:
        # Log exceptions if the request handling itself fails
        full_logger.error(f"Exception during request processing: {e}", exc_info=True)
        # Re-raise or return a generic error response
        raise e # Or return Response("Internal Server Error", status_code=500)

    # 3. Log Response Status and Headers
    res_headers = dict(response.headers)
    filtered_res_headers = filter_headers(res_headers, is_response_headers=True)
    # Try to get HTTP version from scope, default to 1.1
    http_version = request.scope.get('http_version', '1.1')
    log_entry.append(f"RESPONSE: HTTP/{http_version} {response.status_code}")
    for key, value in filtered_res_headers.items():
        log_entry.append(f"{key}: {value}")
    log_entry.append("") # Blank line before body

    # 4. Log Response Body (conditionally and carefully)
    resp_body_content = b""
    if isinstance(response, StreamingResponse):
        # Consume the stream chunk by chunk to log and rebuild
        async for chunk in response.body_iterator:
            resp_body_content += chunk
            if len(resp_body_content) >= MAX_BODY_LOG_SIZE:
                break # Stop reading if limit reached
        # Re-create the response so it can be returned
        response = Response(content=resp_body_content, status_code=response.status_code,
                            headers=dict(response.headers), media_type=response.media_type)
    else:
        # For regular Responses, body is already available
        resp_body_content = getattr(response, 'body', b'') # Access body safely

    if not resp_body_content:
         log_entry.append("[No response body]")
    else:
        content_type = response.headers.get("content-type")
        if is_text_content_type(content_type):
            try:
                 # Decode and truncate
                 body_str = resp_body_content.decode('utf-8', errors='replace')[:MAX_BODY_LOG_SIZE]
                 log_entry.append(body_str)
                 if len(resp_body_content) > MAX_BODY_LOG_SIZE:
                     log_entry.append("... [truncated]")
            except Exception as e:
                 log_entry.append(f"[Error decoding response body as text: {e}]")
        else:
            log_entry.append("[Non-text response body]")


    # 5. Write the combined entry to the full log file
    full_logger.info("\n".join(log_entry))

    return response


# Global Game State
clients = {}  # Dict mapping player_id to {"ws": websocket, ...}
active_usernames = set()  # Track usernames of currently connected players

game_start_time = None  # Start time of current game session
game_duration = 300     # 5 minutes in seconds
food_instances = []     # List storing all food objects

# World dimensions (based on 9x9 grid of a 1920x1080 background)
bgWidth = 1920
bgHeight = 1080
worldWidth = bgWidth * 9
worldHeight = bgHeight * 9


def generate_food():
    """Create new food items and store them globally."""
    global food_instances
    food_instances = []
    for _ in range(1000):  # Generate 1000 food items
        food_instances.append({
            "x": random.randint(0, worldWidth),
            "y": random.randint(0, worldHeight),
            "id": str(uuid4())
        })


# --- Helper Functions for Respawn & Invulnerability ---
async def schedule_respawn(loser_id: str):
    """Waits for a delay, respawns the player at a random location, then sends a respawn message."""
    respawn_delay = 10
    await asyncio.sleep(respawn_delay)
    if loser_id in clients:  # Check if the client is still connected
        new_x = random.randint(0, worldWidth)
        new_y = random.randint(0, worldHeight)
        clients[loser_id]["x"] = new_x
        clients[loser_id]["y"] = new_y
        # (Power was already reset before marking as respawning)
        loser_ws = clients[loser_id]["ws"]
        try:
            await loser_ws.send_json({
                "type": "respawn",
                "x": new_x,
                "y": new_y
            })
            # Clear the respawning flag and re-enable invulnerability after respawn
            clients[loser_id]["is_respawning"] = False
            clients[loser_id]["isInvulnerable"] = True
            asyncio.create_task(end_invulnerability(loser_id, 10))
        except Exception as e:
            print(f"Error sending respawn message to {loser_id}: {e}")


async def end_invulnerability(player_id: str, duration: int):
    """Waits for a given duration then disables a player's invulnerability."""
    await asyncio.sleep(duration)
    if player_id in clients:
        clients[player_id]["isInvulnerable"] = False


async def broadcast_message(message: dict):
    """Sends a JSON message to all currently connected clients."""
    current_websockets = [info["ws"] for info in clients.values() if "ws" in info]
    for ws in current_websockets:
        try:
            await ws.send_json(message)
        except (WebSocketDisconnect, RuntimeError) as e:
            print(f"Error during broadcast: {e}")
            # Cleanup will be handled in the game loop if needed


# --- Central Game Loop ---
async def game_loop():
    global game_start_time, food_instances

    while True:
        current_time = time.time()

        # Wait until the game has been started
        if game_start_time is None:
            await asyncio.sleep(1 / 30)
            continue

        # Calculate remaining game time
        time_remaining = max(0, game_duration - (current_time - game_start_time))

        # --- Game Over & Reset Logic ---
        if time_remaining <= 0:
            # Determine winner if any clients are connected
            if clients:
                winner_id, winner_data = max(clients.items(), key=lambda x: x[1]["power"])
                winner_username = winner_data["username"] or "Guest"
            else:
                winner_username = "No players"
            # Broadcast game over to all clients
            for client in clients.values():
                try:
                    await client["ws"].send_json({
                        "type": "game_over",
                        "winner": winner_username
                    })
                except Exception as e:
                    print(f"Error sending game_over message: {e}")

            # Make every player invulnerable during reset countdown
            for client in clients.values():
                client["isInvulnerable"] = True
                client["is_respawning"] = False

            # Display winner for a short duration
            await asyncio.sleep(5)
            # Notify clients that a new game will start soon
            await broadcast_message({
                "type": "pre_reset_timer",
                "duration": 10
            })
            await asyncio.sleep(10)

            # --- Reset Game State ---
            game_start_time = time.time()
            generate_food()
            for client in clients.values():
                client["power"] = 1
                client["x"] = random.randint(0, worldWidth)
                client["y"] = random.randint(0, worldHeight)
                client["is_respawning"] = False
                client["isInvulnerable"] = True
                # Start invulnerability countdown after reset
                # (Pass the player_id to end_invulnerability)
                asyncio.create_task(end_invulnerability(client_id=next(
                    pid for pid, info in clients.items() if info == client), duration=10))
            for client in clients.values():
                try:
                    await client["ws"].send_json({
                        "type": "game_reset",
                        "time_remaining": game_duration,
                        "food": food_instances
                    })
                except Exception as e:
                    print(f"Error sending game_reset: {e}")
            # Restart the loop immediately after resetting
            continue

        # --- Process Food Collisions ---
        for player_id, client in list(clients.items()):
            player_x = client["x"]
            player_y = client["y"]
            food_to_remove = []
            for food in food_instances:
                distance = ((player_x - food["x"]) ** 2 + (player_y - food["y"]) ** 2) ** 0.5
                if distance < 50:  # Food collection radius
                    food_to_remove.append(food)
                    client["power"] += 1  # Increase player power
            if food_to_remove:
                for food in food_to_remove:
                    if food in food_instances:
                        food_instances.remove(food)
                # Optionally notify the client (or all clients) about removed food
                for client in clients.values():
                    try:
                        await client["ws"].send_json({
                            "type": "food_update",
                            "removed_food": [food["id"] for food in food_to_remove]
                        })
                    except Exception as e:
                        print(f"Food update error: {e}")

        # --- Process Player-to-Player Collisions ---
        current_player_ids = list(clients.keys())
        processed_collisions = set()
        for p1_id in current_player_ids:
            if p1_id not in clients or p1_id in processed_collisions:
                continue

            for p2_id in current_player_ids:
                if p1_id == p2_id or p2_id not in clients or p2_id in processed_collisions:
                    continue

                # Skip if either player is respawning or invulnerable
                if (clients[p1_id].get("is_respawning") or
                        clients[p2_id].get("is_respawning") or
                        clients[p1_id].get("isInvulnerable") or
                        clients[p2_id].get("isInvulnerable")):
                    continue

                p1 = clients[p1_id]
                p2 = clients[p2_id]
                distance = ((p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2) ** 0.5

                if distance < 75:  # Collision detected
                    processed_collisions.add(p1_id)
                    processed_collisions.add(p2_id)

                    # Determine the winner/loser based on power (or randomly on a tie)
                    if p1["power"] > p2["power"]:
                        winner_id, loser_id = p1_id, p2_id
                    elif p2["power"] > p1["power"]:
                        winner_id, loser_id = p2_id, p1_id
                    else:
                        winner_id = random.choice([p1_id, p2_id])
                        loser_id = p2_id if winner_id == p1_id else p1_id

                    # Process the win/loss effect
                    if winner_id and loser_id:
                        clients[winner_id]["power"] += max(clients[loser_id]["power"], 1)
                        clients[loser_id]["power"] = 1  # Reset loser's power
                        clients[loser_id]["is_respawning"] = True
                        try:
                            # Notify the loser they were "eaten"
                            asyncio.create_task(clients[loser_id]["ws"].send_json({"type": "eaten"}))
                        except Exception as e:
                            print(f"Error sending 'eaten' message: {e}")
                        # Schedule the respawn process for the loser
                        asyncio.create_task(schedule_respawn(loser_id))
                    break

        # --- Broadcast Current Game State ---
        state = {
            "type": "players",
            "players": {
                pid: {
                    "x": info["x"],
                    "y": info["y"],
                    "power": info["power"],
                    "username": info["username"],
                    "is_respawning": info.get("is_respawning", False),
                    "isInvulnerable": info.get("isInvulnerable", False)
                }
                for pid, info in clients.items() if "ws" in info
            },
            "time_remaining": time_remaining,
            "food": food_instances
        }

        # Iterate over clients and send updated state
        for pid, client in list(clients.items()):
            try:
                await client["ws"].send_json(state)
            except (WebSocketDisconnect, RuntimeError) as e:
                print(f"Client {pid} disconnected during state broadcast: {e}")
                # Clean up on error
                if client.get("username"):
                    active_usernames.discard(client["username"])
                del clients[pid]

        await asyncio.sleep(1 / 30)  # Run at roughly 30 FPS


# --- WebSocket Endpoint ---
@app.websocket("/ws/game")
async def game_ws(websocket: WebSocket):
    global game_start_time
    # Check for existing connection if the user is logged in.
    session_token = websocket.cookies.get("session_token")
    username = None
    if session_token:
        # Assume get_current_user() is defined elsewhere
        username = await get_current_user(session_token)
        if username in active_usernames:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "message": "Already connected in another tab."
            })
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="User already connected"
            )
            print(f"Rejected connection for user {username}: already connected.")
            return

    # Start game on the first connection
    if game_start_time is None and len(clients) == 0:
        game_start_time = time.time()
        generate_food()
        if not hasattr(app.state, "game_loop_task"):
            app.state.game_loop_task = asyncio.create_task(game_loop())

    await websocket.accept()
    player_id = str(uuid4())
    if username:
        active_usernames.add(username)

    # Initialize new client state
    clients[player_id] = {
        "ws": websocket,
        "x": worldWidth / 2,
        "y": worldHeight / 2,
        "power": 1,
        "username": username,
        "is_respawning": False,
        "isInvulnerable": True  # New players start invulnerable
    }
    # Start invulnerability timer
    asyncio.create_task(end_invulnerability(player_id, 10))

    # Send initial details to the client
    time_remaining = max(0, game_duration - (time.time() - game_start_time))
    await websocket.send_json({
        "type": "id",
        "id": player_id,
        "time_remaining": time_remaining,
        "food": food_instances
    })

    # Now simply receive position updates from the client
    try:
        while True:
            data = await websocket.receive_json()
            # Update player's position based on received data
            clients[player_id]["x"] = data["x"]
            clients[player_id]["y"] = data["y"]
    except WebSocketDisconnect:
        # Cleanup after disconnection
        if clients.get(player_id, {}).get("username"):
            active_usernames.discard(clients[player_id]["username"])
        clients.pop(player_id, None)


@app.get("/", response_class=FileResponse)
async def serve_home_page():
    # Serve the main index page
    # Check if file exists? Add error handling if needed.
    return FileResponse("public/index.html")

@app.get("/play", response_class=HTMLResponse)
async def game_page(request: Request):
    return templates.TemplateResponse("game.html", {"request": request})

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
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    salt = user.get("salt", "")
    if not verify_password(credentials.password, salt, user["hashed_password"]):
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
    DISALLOWED_CHARS = {
    '<', '>', '"', "'", '&',   # HTML/XML injection
    '/', '\\',                 # Path traversal
    '{', '}', '[', ']',        # Template/JSON injection
    ';',                       # Command injection
    '=', '(', ')',             # Code execution risks
    '|', '!', '`',             # Shell/Pipeline risks
    '$', '*', '~'              # Regex/special chars
    }
    for char in credentials.username:
        if char in DISALLOWED_CHARS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username contains invalid characters."
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
    salt, hashed_password = get_password_hash(credentials.password)

    # Store the new user.
    users_collection.insert_one({
        "username": credentials.username,
        "salt": salt,
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


# --- Game Specific API Endpoints ---

@app.get("/api/game/status")
async def get_game_status(username: Optional[str] = Depends(get_current_user)):
    """Checks if the currently logged-in user is already in an active game."""
    if username and username in active_usernames:
        return {"in_game": True}
    else:
        return {"in_game": False}

# --- Logging Middleware and Functions (Keep as is) ---

def request_log(request : Request, response : Response ):
   tim = datetime.datetime.now()
   content ="time: "+ tim.strftime("%m/%d/%Y, %H:%M:%S") + "\n client " + str(request.client.host)+"\n method " + str(request.method) + "\n url path " + str(request.url.path) + '\n response code ' + str(response.status_code) +"\n\n"
   with open("/request_logs/request_logs.txt", "a") as f:
        f.write(content)

def fullLogging(request : Request, response : Response ):
    req = b""
    reqS = request.method + request.url.path
    for header in request.headers:
        reqS = reqS + header +": "+ request.headers[header]# need to take out auth tokens and handle cookies better
    req = reqS.encode() + b"\n"
    res = b""
    with open("/fullreq.txt","ab") as f:
        f.write(req)
    with open("/fullres.txt","ab") as f:
        f.write(res)

#to do docker logs, volume
def errorLog(error : string, tb : string):
    content = "error: " + error + "\n" + "traceback: "+ tb +"\n\n"
    with open("/error_log.txt","b") as f:
        f.write(content)
'''
# full request and response logs
@app.middleware("http")
async def reqresLogging(request: Request, call_next):
    #try:
    response = await call_next(request)
    #except Exception as e:
    # erro = str(e)
    #tb = traceback.format_exe()
    #errorLog(e,tb)
    #return
    request_log(request,response)
    #fullLogging(request,response)
    return response # Return the actual response now
'''
# --- Remove duplicate /login route and /hello/{name} ---

# --- Add main execution block (optional, for running directly) ---
#if __name__ == "__main__":
#    uvicorn.run(app, host="0.0.0.0", port=8000)
leaderboard = []#list of dicts containing size and user
player_dict = {}#will be added to when new user joins, username:player
class Player:
    def __init__(self, username):
        self.username = username #these are stand in numbers if you want to change them
        self.position_x : int
        self.position_y : int
        self.size = 20 #starting size
        #self.speed = 5
        #self.debuffs = {"debuff_speed":False,"debuff_size":False }#assuming maybe 2 debuffs and 2 buffs, increase and decrease size and speed temp
        #self.buffs = {"buff_speed":False,"buff_size":False }

food_dict ={}
class Food:
    def __init__(self, foodId, x,y):
        self.position_x = x
        self.position_y = y
        self.idd = foodId

def recievedMove(jsonMessage: string):#updates the player dict to players new position #does not return json position
    message = json.loads(jsonMessage)
    username = message["username"]
    player = player_dict.get(username)
    player.position_x = message["x"]
    player.position_y = message["y"]
    player_dict[username] = player

#call after new player
def add_player(jsonMessage: string):
    message = json.loads(jsonMessage)
    username = message["username"]
    player = Player(username)
    player_dict[username] = player #adds player to player dict

def add_food(jsonMessage: string): #call after new food
    message = json.loads(jsonMessage)
    foodId = message["foodId"]
    x = message["x"]
    y = message["y"]
    food = Food(foodId, x,y)
    food_dict[food.idd] = food

def get_leaderboard():
    pass

#sends the position, size, username, of all players, sends id and position of all food for new player
def initial(jsonMessage : string): #creates json object {"type":init,"username":newplayerusername,"players":[{"username":username,'x':int,'y':int,"size":int}...],"foods":[{'idd':str,'x':int,'y':int}...]}
    dict0 = json.loads(jsonMessage)
    dict1 = {"type":"init","username":dict0.username}
    players = []
    for player in player_dict.values():
        dict2 = {"username":player.username,"x":player.position_x,"y":player.position_y,"size":player.size}
        players.append(dict2)
    foods=[]
    for food in food_dict.values():
        dict3 = {"id":food.id,"x":food.position_x,"y":food.position_y}
        foods.append(dict3)
    dict1["players"] = players
    dict1["foods"] = foods
    jInit = json.dumps(dict1)
    return jInit

def GetsPositionsJson():#gets the json message of all the positions to all users
    dict1 = {"type":"update"} #{"type":"update","players":[{"username":str,"x":int,"y":int,"size":int}....]}
    players = []
    for player in player_dict.values():
        dict2 = {"username":player.username,"x":player.position_x,"y":player.position_y, "size":player.size}
        players.append(dict2)
    dict1["players"] = players
    jUpdate = json.dumps(dict1)
    return jUpdate

#recieves ate food message
def ate_food(jsonMessage: string):#{"type":"ate_food","username":username,"idd":foodId,"size":player size}
    message = json.loads(jsonMessage)
    username = message["username"]
    foodId = message["idd"]
    player = player_dict.get(username)
    player.size = player.size + 1
    player_dict[username] = player
    del food_dict[foodId]
    dict1 = {"type":"ate_food","username":username,"idd":foodId,"size":player.size}
    jMess = json.dumps(dict1)
    return jMess


def winner(player1, player2):#returns dict with winner and loser #might want to comment out later but I'm unsure if we're deciding who is ate client or server side
    if player1.size > player2.size:
        player1.size += player2.size #player 1 gets player 2 size
        #speed_update(player1) #updates player 1 speed
        player_dict[player1.username] = player1
        del player_dict[player2.username]  # player 2 loses and is deleted from player_dict
        return {"loser":player2,"winner":player1} #return player2 to broadcast defeat?
    elif player1.size < player2.size:
        player2.size += player1.size  # player 1 gets player 2 size
        #speed_update(player2)
        player_dict[player2.username] = player2
        del player_dict[player1.username]
        return {"loser":player1, "winner":player2}
    else:
        p = random.choice([player1, player2])
        if p.username == player1.username:#player 1 is decided winner
            player1.size += player2.size #increase player 1 by player2 size
            #speed_update(player1) #update speed
            player_dict[player1.username] = player1
            del player_dict[player2.username]  # del player 2
            return {"loser":player2,"winner":player1} #return player2 to broadcast defeat?
        else:#player 2 is decided winner
            player2.size += player1.size
            #speed_update(player2)
            player_dict[player2.username] = player2
            del player_dict[player1.username]
            return {"loser":player1, "winner":player2}


'''''
def add_buff_debuff(player : Player, buff : string):
    if buff in player.debuffs:
        player.debuffs[buff] = True
        if buff == "debuff_speed":
            if player.speed > 1:
                player.speed = player.speed - 1
        else: #debuff_size
            if player.size>=25:
                player.size = player.size - 5
            else:
                player.size = 20
    if buff in player.buffs:
        player.buffs[buff] = True
        if buff == "buff_speed":
            player.speed = player.speed + 1
        if buff == "buff_size":
            player.size = player.size + 5
    player_dict[player.username] = player
    return player

def remove_buff_debuff(player : Player, buff : string): #maybe should be on a seperate thread to time it, threading.timer(wait, function)
    if buff in player.debuffs:
        if buff == "debuff_speed":
            player.speed = player.speed + 1
        else:
            player.size = player.size + 5
        player.debuffs[buff] = False
    if buff in player.buffs:
        player.buffs[buff] = False
        if buff == "buff_speed":
            if player.speed > 1:
                player.speed = player.speed - 1
        else:
            if player.size>=25:
                player.size = player.size - 5
            else:
                player.size = 20
    player_dict[player.username] = player
    return player

#if we are following agar.io bigger size will mean slower speeds, to be called after eating
def speed_update(player):
    if player.size >= 100:#these are all stand-in values for now feel free to change
        player.speed = 1
    elif player.size >= 75:
        player.speed = 2
    elif player.size >= 50:
        player.speed = 3
    elif player.size >= 25:
        player.speed = 4
    else:
        player.speed = 5
    if player.buffs == "buff_speed": #making sure is consistent with buffs/debuffs #hopefully debuffs/buffs doesn't change within the function
        player.speed = player.speed + 1
    if player.debuffs == "debuff_speed":
        if player.speed > 1:
            player.speed = player.speed - 1
    player_dict[player.username] = player
    return player
'''


