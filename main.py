import hashlib
import traceback
import uvicorn
import asyncio
import json
from fastapi import FastAPI, Request, Depends, HTTPException, status, Response, Cookie, Body, WebSocket, WebSocketDisconnect, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from database import users_collection, sessions_collection, leaderboard_stats_collection, skin_collection, \
    playerStats_collection
from typing import Optional
from logger_help import RequestResponseLogger
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
from typing import Optional
from PIL import Image, ImageDraw, ImageChops
import uuid
from io import BytesIO
from starlette.responses import StreamingResponse


#from traceback import extract_stack, format_list
app = FastAPI(title='Merge Conflict Game', description='Authentication and Game API', version='1.0')
app.add_middleware(RequestResponseLogger)

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

clients = {}
active_usernames = set()

# Add these at the top with other global variables
game_start_time = None
game_duration = 300   # 5 minutes in seconds
food_instances = []  # List to store food positions

# World dimensions based on 9x9 grid of 1920x1080 background
bgWidth = 1920
bgHeight = 1080
worldWidth = bgWidth * 9
worldHeight = bgHeight * 9

def generate_food():
    global food_instances
    food_instances = []
    for _ in range(1000):  # Decreased from 3000 to 1500 food items
        food_instances.append({
            "x": random.randint(0, worldWidth),
            "y": random.randint(0, worldHeight),
            "id": str(uuid4())
        })

# --- Helper Function to update persistent score ---
async def update_total_score(username: str, score_increase: int):
    if not username: # Don't track scores for guests
        return
    if score_increase <= 0: # Don't record zero or negative score changes
        return
    try:
        leaderboard_stats_collection.update_one(
            {"username": username},
            {"$inc": {"total_score": score_increase}},
            upsert=True
        )
        print(f"Updated total score for {username} by {score_increase}")
        # --- Update lifetime score and check achievements ---
        users_collection.update_one(
            {"username": username},
            {"$inc": {"total_score_lifetime": score_increase}},
            # No upsert needed here, user must exist if we are updating score
        )
        # Check for achievements after score update
        asyncio.create_task(check_and_grant_achievements(username))
        # --- End Achievement Check ---
    except Exception as e:
        print(f"Error updating total score for {username}: {e}")

# --- Helper Function for Delayed Respawn ---
async def schedule_respawn(loser_id: str):
    """Waits respawn_delay seconds, calculates new position, updates state, and sends respawn message."""
    respawn_delay = 10 # Increased respawn delay
    await asyncio.sleep(respawn_delay)
    if loser_id in clients: # Check if client still connected
        new_x = random.randint(0, worldWidth)  # Respawn randomly
        new_y = random.randint(0, worldHeight)
        clients[loser_id]["x"] = new_x
        clients[loser_id]["y"] = new_y
        # Note: Power was already reset to 1 earlier

        loser_ws = clients[loser_id]["ws"]
        try:
            await loser_ws.send_json({
                "type": "respawn",
                "x": new_x,
                "y": new_y
            })
            # Clear the respawning flag now that they have respawned
            clients[loser_id]["is_respawning"] = False

            # Make player invulnerable after respawn
            clients[loser_id]["isInvulnerable"] = True
            invulnerability_duration = 10 # Match client-side setting
            asyncio.create_task(end_invulnerability(loser_id, invulnerability_duration))
        except Exception as e:
            print(f"Error sending respawn message to {loser_id}: {e}")

# --- Helper Function to End Invulnerability ---
async def end_invulnerability(player_id: str, duration: int):
    """Waits for the duration and sets the player's invulnerability flag to False."""
    await asyncio.sleep(duration)
    if player_id in clients:
        clients[player_id]["isInvulnerable"] = False







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
    log_format = '%(asctime)s - %(client_ip)s - %(method)s - %(path)s - %(message)s'
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
ERROR_FILE = Path("/app/host_mount/error_logs.log")
REG_LOGIN_FILE = Path("/app/host_mount/reg_login.log")
error_logger = logging.getLogger("error_logger")
error_logger.setLevel(logging.ERROR)
loginReg_logger = logging.getLogger("login_reg_logger")
loginReg_logger.setLevel(logging.INFO)
if not error_logger.handlers:#honestly not sure if this line is needed but the other one has it and I should try to be consistent
    error_handler = logging.FileHandler(ERROR_FILE)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s\n"))
    error_logger.addHandler(error_handler)
if not loginReg_logger.handlers:
    login_handler = logging.FileHandler(REG_LOGIN_FILE)
    login_handler.setLevel(logging.INFO)
    login_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s\n"))
    loginReg_logger.addHandler(login_handler)

@app.middleware("http")
async def log_requests_and_responses(request: Request, call_next):
    try:
        username = ''
        if "session_token" in request.cookies:
            tok = request.cookies.get("session_token")
            hash_tok = hash_token(tok)
            dicty = sessions_collection.find_one({"token_hash": hash_tok})
            if dicty is not None:
                username = dicty["username"]
        client_ip = request.headers.get("x-real-ip", request.client.host if request.client else "unknown")
        log_entry = []

        # 1. Log Request Line and Headers
        req_headers = dict(request.headers)
        filtered_req_headers = filter_headers(req_headers)
        log_entry.append(f"REQUEST: {request.method} {request.url.path} HTTP/{request.scope.get('http_version', '1.1')}")
        for key, value in filtered_req_headers.items():
            log_entry.append(f"{key}: {value}")
        log_entry.append("")  # Blank line before body

        # 2. Log Request Body (conditionally)
        request_body = await request.body()  # Read body ONCE
        should_redact_body = request.method == "POST" and request.url.path in SENSITIVE_PATHS

        if should_redact_body:
            log_entry.append("[Request body redacted for sensitive endpoint]")
        elif request_body:
            content_type = request.headers.get("content-type")
            if is_text_content_type(content_type):
                try:
                    body_str = request_body.decode('utf-8', errors='replace')[:MAX_BODY_LOG_SIZE]
                    log_entry.append(body_str)
                    if len(request_body) > MAX_BODY_LOG_SIZE:
                        log_entry.append("... [truncated]")
                except Exception as e:
                    log_entry.append(f"[Error decoding request body as text: {e}]")
            else:
                log_entry.append("[Non-text request body]")
        else:
            log_entry.append("[Empty body]")
        log_entry.append("-" * 20)  # Separator

        # --- Pass request (with potentially consumed body) to the endpoint ---
        try:
            response = await call_next(request)
        except Exception as e:
            err_s = str(e)
            tbs = traceback.format_exc()
            combo = err_s + "\n" + tbs
            error_logger.error(combo)
            return Response("Internal Server Error", status_code=500)

        # 3. Log Response Status and Headers
        res_headers = dict(response.headers)
        filtered_res_headers = filter_headers(res_headers, is_response_headers=True)
        http_version = request.scope.get('http_version', '1.1')
        log_entry.append(f"RESPONSE: HTTP/{http_version} {response.status_code}")
        for key, value in filtered_res_headers.items():
            log_entry.append(f"{key}: {value}")
        log_entry.append("")  # Blank line before body

        # 4. Log Response Body (conditionally and carefully)
        resp_body_content = b""

        if isinstance(response, StreamingResponse):
            # For StreamingResponse, collect the body while rebuilding it for the client
            async def generate_response():
                nonlocal resp_body_content
                async for chunk in response.body_iterator:
                    resp_body_content += chunk
                    if len(resp_body_content) >= MAX_BODY_LOG_SIZE:
                        break  # Stop reading if limit reached
                    yield chunk  # Yield back chunks to the client

            # Recreate the StreamingResponse
            response = StreamingResponse(generate_response(), status_code=response.status_code,
                                         headers=dict(response.headers), media_type=response.media_type)
        else:
            # For regular Responses, body is already available
            resp_body_content = getattr(response, 'body', b'')  # Access body safely

        # Check if we have any content in the response body
        if not resp_body_content:
            log_entry.append("[No response body]")
        else:
            content_type = response.headers.get("content-type")
            if is_text_content_type(content_type):
                try:
                    body_str = resp_body_content.decode('utf-8', errors='replace')[:MAX_BODY_LOG_SIZE]
                    log_entry.append(body_str)
                    if len(resp_body_content) > MAX_BODY_LOG_SIZE:
                        log_entry.append("... [truncated]")
                except Exception as e:
                    log_entry.append(f"[Error decoding response body as text: {e}]")
            else:
                log_entry.append("[Non-text response body]")

        # DEBUG: Check if the log entry is being generated
        full_logger.debug(f"Full log entry: \n{log_entry}")  # Debug the full log entry

        # 5. Write the combined entry to the full log file
        full_logger.info("\n".join(log_entry))

        # Log to the simple request logger
        request_logger.info("Username: " + username + " Response Status: " + str(response.status_code), extra={
            "client_ip": client_ip,
            "method": request.method,
            "path": request.url.path,
        })

        return response

    except Exception as e:
        err_s = str(e)
        tbs = traceback.format_exc()
        combo = err_s + "\n" + tbs
        error_logger.error(combo)










broadcast_task = None
broadcast_stop_event = asyncio.Event()
time_remaining = 0

def start_broadcast_loop():
    global broadcast_task, broadcast_stop_event
    if broadcast_task is None or broadcast_task.done():
        broadcast_stop_event.clear()
        broadcast_task = asyncio.create_task(broadcast_loop())

def stop_broadcast_loop():
    broadcast_stop_event.set()

async def broadcast_loop():
    try:
        while not broadcast_stop_event.is_set():
            await broadcast_state()
            await asyncio.sleep(1 / 30)  # 30 times per second
    except asyncio.CancelledError:
        pass  # Task was cancelled

async def broadcast_state():
    # --- Your original broadcast logic ---
    global time_remaining, game_start_time, food_instances, active_usernames
    current_clients_items = list(clients.items())  # Copy items to prevent modification issues
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
            for pid, info in current_clients_items
            if "ws" in info
        },
        "time_remaining": time_remaining,
        "food": food_instances
    }

    clients_to_remove = []
    for pid, client in current_clients_items:
        try:
            if "ws" in client:
                await client["ws"].send_json(state)
        except (WebSocketDisconnect, RuntimeError) as e:
            print(f"Client {pid} disconnected during broadcast or send error: {e}")
            clients_to_remove.append(pid)

    for pid in clients_to_remove:
        if pid in clients:
            disconnected_client = clients.pop(pid)
            disconnected_username = disconnected_client.get("username")
            disconnected_score = disconnected_client.get("power", 0)
            if disconnected_username:
                active_usernames.discard(disconnected_username)
                await update_total_score(disconnected_username, disconnected_score)


@app.websocket("/ws/game")
async def game_ws(websocket: WebSocket):
    try:
        global game_start_time, food_instances, active_usernames, time_remaining

        # --- Check for existing connection for logged-in users ---
        session_token = websocket.cookies.get("session_token")
        username = None
        if session_token:
            username = await get_current_user(session_token)
            if username in active_usernames:
                # User is already connected, reject this new connection
                await websocket.accept() # Accept briefly to send the message
                await websocket.send_json({"type": "error", "message": "Already connected in another tab."})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User already connected")
                print(f"Rejected connection for user {username}: already connected.")
                return # Stop further execution for this connection
        # --- End check ---

        # Start the game timer if this is the first connection
        if game_start_time is None and len(clients) == 0:
            game_start_time = time.time()
            generate_food()  # Generate initial food
            start_broadcast_loop()
        await websocket.accept()
        player_id = str(uuid4())
        if username:
            active_usernames.add(username)
        clients[player_id] = {
            "ws": websocket,
            "x": worldWidth / 2,  # Spawn in center
            "y": worldHeight / 2,  # Spawn in center
            "power": 1,
            "username": username,
            "is_respawning": False,
            "isInvulnerable": True # Player starts invulnerable
        }

        # Start invulnerability timer for new player
        invulnerability_duration = 10 # Match client-side setting
        asyncio.create_task(end_invulnerability(player_id, invulnerability_duration))

        # Send back the ID, game time remaining, and initial food positions
        time_remaining = max(0, game_duration - (time.time() - game_start_time)) if game_start_time else game_duration
        await websocket.send_json({
            "type": "id",
            "id": player_id,
            "time_remaining": time_remaining,
            "food": food_instances
        })

        try:
            while True:
                # Check if game time is up
                current_time = time.time()
                time_remaining = max(0, game_duration - (current_time - game_start_time)) if game_start_time else game_duration

                if time_remaining <= 0 and game_start_time is not None:
                    # Game over - determine winner
                    winner_username = "Guest"
                    if clients: # Check if any clients are left to determine a winner
                        winner = max(clients.items(), key=lambda x: x[1]["power"])
                        winner_username = winner[1].get("username") or "Guest"

                        if winner_username == username:
                            stats = playerStats_collection.find_one({"username": winner_username})

                            # print(winner_username)
                            playerStats_collection.update_one(
                                {"username": winner_username},  # Match by username
                                {"$set": {"gamesWon": stats["gamesWon"] + 1}},  # Update the selected field
                                upsert=True  # Create a new document if none exists
                            )

                    winner_display_duration = 5 # How long to show winner name
                    reset_countdown_duration = 10 # How long the "New game starting" countdown lasts

                    # Send game over message to all clients
                    for client in clients.values():
                        try:
                            await client["ws"].send_json({
                                "type": "game_over",
                                "winner": winner_username
                            })
                        except:
                            print(f"Error sending game_over message to a client.")
                            pass # Ignore errors for disconnected clients

                    # --- Make all players invulnerable during reset countdown ---
                    for pid in clients:
                        if pid in clients: # Check they didn't disconnect right now
                            clients[pid]["isInvulnerable"] = True
                            clients[pid]["is_respawning"] = False # Ensure this is false too
                    # --- End Invulnerability Set ---

                    # Wait briefly for winner display
                    await asyncio.sleep(winner_display_duration)

                    # --- Send pre-reset countdown trigger ---
                    await broadcast_message({
                        "type": "pre_reset_timer",
                        "duration": reset_countdown_duration
                    })
                    # --- End pre-reset trigger ---

                    # Wait for the countdown duration before actually resetting
                    await asyncio.sleep(reset_countdown_duration)

                    # --- Update persistent scores for all remaining players ---
                    update_tasks = []
                    games_played_updates = [] # Track users whose games_played needs update
                    for client_id, client_info in list(clients.items()): # Iterate over a copy
                        if client_id in clients: # Check if still connected
                            username = client_info.get("username")
                            score = client_info.get("power", 0)
                            if username:
                                update_tasks.append(update_total_score(username, score))
                                games_played_updates.append(username)
                    if update_tasks:
                        await asyncio.gather(*update_tasks)
                    # --- Update games played count & check achievements ---
                    if games_played_updates:
                        users_collection.update_many(
                            {"username": {"$in": games_played_updates}},
                            {"$inc": {"games_played": 1}}
                        )
                        # Check achievements for all players who finished the game
                        achievement_check_tasks = [check_and_grant_achievements(uname) for uname in games_played_updates]
                        await asyncio.gather(*achievement_check_tasks)
                    # --- End Games Played Update ---
                    # Reset game state
                    game_start_time = time.time()  # Reset timer
                    generate_food()  # Generate new food
                    invulnerability_duration = 10 # Duration for post-reset invulnerability
                    for client_id in clients:
                        clients[client_id]["power"] = 1  # Reset all powers to 1
                        clients[client_id]["x"] = random.randint(0, worldWidth)  # Random respawn
                        clients[client_id]["y"] = random.randint(0, worldHeight)
                        clients[client_id]["is_respawning"] = False # Ensure respawn flag is clear
                        clients[client_id]["isInvulnerable"] = True # Grant invulnerability
                        # Start timer to end invulnerability
                        asyncio.create_task(end_invulnerability(client_id, invulnerability_duration))

                    # Send reset message to all clients
                    for client in clients.values():
                        try:
                            await client["ws"].send_json({
                                "type": "game_reset",
                                "time_remaining": game_duration,
                                "food": food_instances
                            })
                        except:
                            pass

                data = await websocket.receive_json()
                clients[player_id]["x"] = data["x"]
                clients[player_id]["y"] = data["y"]

                # Check for food collisions
                player_x = clients[player_id]["x"]
                player_y = clients[player_id]["y"]
                food_to_remove = []

                for food in food_instances:
                    distance = ((player_x - food["x"]) ** 2 + (player_y - food["y"]) ** 2) ** 0.5
                    if distance < 50:  # Increased from 30 to 50 for food collection radius
                        food_to_remove.append(food)
                        clients[player_id]["power"] += 1
                        # --- Check score achievements after power increase ---
                        current_username = clients[player_id].get("username")
                        current_power = clients[player_id]["power"]
                        if current_username:
                            asyncio.create_task(check_in_game_score_achievements(current_username, current_power))
                        # --- End Achievement Check --
                # Remove collected food and notify all clients
                if food_to_remove:

                    stats = playerStats_collection.find_one({"username": username})

                    playerStats_collection.update_one(
                        {"username": username},  # Match by username
                        {"$set": {"pellets": stats["pellets"] + 1}},  # Update the selected field
                        upsert=True  # Create a new document if none exists
                    )

                    for food in food_to_remove:
                        food_instances.remove(food)
                    # Send food update to all clients
                    for client in clients.values():
                        try:
                            await client["ws"].send_json({
                                "type": "food_update",
                                "removed_food": [f["id"] for f in food_to_remove]
                            })
                        except:
                            pass

                # Check for player collisions and update power
                # Store players to process collisions for to avoid modifying during iteration
                current_player_ids = list(clients.keys())
                processed_collisions = set() # Avoid double checks

                for p1_id in current_player_ids:
                    if p1_id not in clients or p1_id in processed_collisions: # Check if player still exists
                        continue

                    for p2_id in current_player_ids:
                        if p1_id == p2_id or p2_id not in clients or p2_id in processed_collisions: # Check if other player exists and not self
                            continue

                        # --- Check if either player is currently respawning ---
                        if clients[p1_id].get("is_respawning", False) or clients[p2_id].get("is_respawning", False):
                            continue # Skip collision check if one is respawning

                        # --- Check if either player is invulnerable ---
                        if clients[p1_id].get("isInvulnerable", False) or clients[p2_id].get("isInvulnerable", False):
                            continue # Skip collision check if one is invulnerable
                        # --- End Checks ---

                        p1 = clients[p1_id]
                        p2 = clients[p2_id]

                        distance = ((p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2) ** 0.5

                        if distance < 75: # Collision detected
                            processed_collisions.add(p1_id)
                            processed_collisions.add(p2_id)

                            winner_id, loser_id = None, None
                            p1_power = p1["power"]
                            p2_power = p2["power"]

                            if p1_power > p2_power:
                                winner_id, loser_id = p1_id, p2_id
                            elif p2_power > p1_power:
                                winner_id, loser_id = p2_id, p1_id
                            else: # Tie
                                chosen_winner = random.choice([p1_id, p2_id])
                                if chosen_winner == p1_id:
                                    winner_id, loser_id = p1_id, p2_id
                                else:
                                    winner_id, loser_id = p2_id, p1_id

                            # Process the win/loss if winner and loser are determined
                            if winner_id and loser_id and winner_id in clients and loser_id in clients: # Double check clients exist
                                winner = clients[winner_id]
                                loser = clients[loser_id]

                                # Add power (only add if loser is not already at 1, prevents negative power)
                                power_gain = loser["power"] if loser["power"] > 1 else 1
                                winner["power"] += power_gain

                                # Reset loser power *immediately* in state
                                loser["power"] = 1
                                loser["is_respawning"] = True # <<< SET RESPAWNING FLAG

                                # Send "eaten" message to loser
                                try:
                                    loser_ws = loser["ws"]
                                    asyncio.create_task(loser_ws.send_json({"type": "eaten"}))
                                except Exception as e:
                                    print(f"Error sending 'eaten' message to {loser_id}: {e}")

                                # --- Check winner's score achievements after power increase ---
                                winner_username = winner.get("username") # Already got this above

                                stats = playerStats_collection.find_one({"username": winner_username})

                                playerStats_collection.update_one(
                                    {"username": winner_username},  # Match by username
                                    {"$set": {"kills": stats["kills"] + 1}},  # Update the selected field
                                    upsert=True  # Create a new document if none exists
                                )

                                new_winner_power = winner["power"]
                                if winner_username:
                                    asyncio.create_task(check_in_game_score_achievements(winner_username, new_winner_power))
                                # --- End Score Achievement Check ---

                                # --- Update winner's eaten count & check achievements ---
                                winner_username = winner.get("username")
                                if winner_username:
                                    users_collection.update_one(
                                        {"username": winner_username},
                                        {"$inc": {"players_eaten_lifetime": 1}}
                                    )
                                    asyncio.create_task(check_and_grant_achievements(winner_username))
                                # --- End Eaten Count Update ---

                                # Schedule the respawn task for the loser
                                asyncio.create_task(schedule_respawn(loser_id))

                            break # Move to next p1_id after processing a collision for p1

        except WebSocketDisconnect:
            # Player disconnecting logic
            disconnected_client = clients.pop(player_id, None)
            if disconnected_client:
                disconnected_username = disconnected_client.get("username")
                disconnected_score = disconnected_client.get("power", 0)
                if disconnected_username:
                    active_usernames.discard(disconnected_username)
                    # --- Update score on disconnect ---
                    await update_total_score(disconnected_username, disconnected_score)
                    # --- End score update ---
                print(f"Player {player_id} disconnected.") # Removed broadcast remove message
                # Broadcast remove message to all remaining clients
                await broadcast_message({
                    "type": "remove",
                    "id": player_id
                })
    except Exception as e:
        err_s = str(e)
        tbs = traceback.format_exc()
        combo = err_s + "\n" + tbs
        error_logger.error(combo)







# --- Helper Function to Broadcast Messages ---
async def broadcast_message(message: dict):
    """Sends a JSON message to all currently connected clients."""
    # Create a copy of client websockets to iterate over, avoiding modification issues
    current_websockets = [info["ws"] for info in clients.values() if "ws" in info]
    for ws in current_websockets:
        try:
            await ws.send_json(message)
        except (WebSocketDisconnect, RuntimeError) as e:
            # Handle potential errors silently during broadcast, main loop handles cleanup
            print(f"Error during broadcast to a client: {e}")
            pass
# --- End Broadcast Helper ---

class PlayerStatsResponse(BaseModel):
    gamesWon: int
    deaths: int
    kills: int
    pellets: int
    skinFileName: str



       # gamesWon=stats["gamesWon"],
      #  deaths=stats["deaths"],
     #   kills=stats["kills"],
    #    pellets=stats["pellets"],

@app.post("/api/addDeaths")
async def add_Deaths(username: Optional[str] = Depends(get_current_user)):
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized: Username is required")

    # Fetch stats from the database using the username
    stats = playerStats_collection.find_one({"username": username})

    playerStats_collection.update_one(
        {"username": username},  # Match by username
        {"$set": {"deaths": stats["deaths"]+1 }},  # Update the selected field
        upsert=True  # Create a new document if none exists
    )

    return

@app.post("/api/addKills")
async def add_Kills(username: Optional[str] = Depends(get_current_user)):

    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized: Username is required")

    # Fetch stats from the database using the username
    stats = playerStats_collection.find_one({"username": username})

    playerStats_collection.update_one(
        {"username": username},  # Match by username
        {"$set": {"kills": stats["kills"]+1 }},  # Update the selected field
        upsert=True  # Create a new document if none exists
    )

    return

@app.get("/api/playerStats", response_model=PlayerStatsResponse)
async def get_player_stats(username: Optional[str] = Depends(get_current_user)):
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized: Username is required")

    # Fetch stats from the database using the username
    stats = playerStats_collection.find_one({"username": username})

    if not stats:
        raise HTTPException(status_code=404, detail="Player stats not found")
    
    # Fetch the user's skin information
    skin = skin_collection.find_one({"username": username})
    
    # Determine the skin filename
    skin_file_name = "PurplePlanet.png"  # Default skin
    
    if skin:
        selected_skin = skin.get("selected", "skin1")
        
        if selected_skin == "custom":
            skin_file_name = skin.get("custom", skin_file_name)
        elif selected_skin == "skin1":
            skin_file_name = "PurplePlanet.png"
        elif selected_skin == "skin2":
            skin_file_name = "RedPlanet.png"
        elif selected_skin == "skin3":
            skin_file_name = "BluePlanet.png"

    # Return stats in the expected format
    return PlayerStatsResponse(
        gamesWon=stats["gamesWon"],
        deaths=stats["deaths"],
        kills=stats["kills"],
        pellets=stats["pellets"],
        skinFileName=skin_file_name
    )

@app.get("/api/playerSprite")
async def get_player_stats(username: Optional[str] = Depends(get_current_user)):
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized: Username is required")

    # Fetch stats from the database using the username
    skin = skin_collection.find_one({"username": username})

    if not skin:
        return {"fileName": "PurplePlanet.png"}

    skinNum = skin.get("selected")
    selected_skin = "PurplePlanet.png"

    if skinNum == "custom":
        selected_skin = skin.get("custom")
    elif skinNum == "skin1"  :
        selected_skin = "PurplePlanet.png"
    elif skinNum == "skin2":
        selected_skin = "RedPlanet.png"
    elif skinNum == "skin3":
        selected_skin = "BluePlanet.png"

    return {"fileName": selected_skin}

class Message(BaseModel):
    message: str

@app.post("/api/getImg")
async def get_player_IMG(data: Message):
    # Access the message from the request body
    username = data.message
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized: Username is required")

    # Fetch stats from the database using the username
    skin = skin_collection.find_one({"username": username})

    if not skin:
        return {"fileName": "PurplePlanet.png"}

    skinNum = skin.get("selected")
    selected_skin = "PurplePlanet.png"

    if skinNum == "custom":
        selected_skin = skin.get("custom")
    elif skinNum == "skin1"  :
        selected_skin = "PurplePlanet.png"
    elif skinNum == "skin2":
        selected_skin = "RedPlanet.png"
    elif skinNum == "skin3":
        selected_skin = "BluePlanet.png"

    # Return a dictionary with the key 'filename' and the received string
    return JSONResponse(content={"fileName": selected_skin})

class SkinSelection(BaseModel):
    selectedSkin: str

@app.post("/api/profile")
async def save_skin(skin: SkinSelection, username: Optional[str] = Depends(get_current_user)):
    """
    Save the selected skin for the current user.
    """
    if not username:
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        # Update or insert the skin selection in the database
        skin_collection.update_one(
            {"username": username},  # Match by username
            {"$set": {"selected": skin.selectedSkin}},  # Update the selected field
            upsert=True  # Create a new document if none exists
        )

        return {"message": "Skin selection saved successfully", "selected": skin.selectedSkin}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save skin: {str(e)}")

@app.get("/profile", response_class=FileResponse)
async def serve_home_page():
    # Serve the main index page
    # Check if file exists? Add error handling if needed.
    return FileResponse("public/Profile.html")

def resize_and_replace_circular_png(filename, target_size):
    """
    Resizes a circular PNG image to the target size and replaces the original file.
    
    Args:
        filename (str): Path to the input PNG file (will be overwritten).
        target_size (int): Desired width and height of the output image in pixels.
    """
    # Open the original image
    original = Image.open(filename).convert("RGBA")
    
    # Create a new transparent image with target size
    resized = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
    
    # Resize the original to fit while maintaining aspect ratio
    original.thumbnail((target_size, target_size), Image.LANCZOS)
    
    # Center the original on the new canvas
    x = (target_size - original.width) // 2
    y = (target_size - original.height) // 2
    resized.paste(original, (x, y), original)
    
    # Create a circular mask
    mask = Image.new("L", (target_size, target_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, target_size, target_size), fill=255)
    
    # Apply the mask
    resized.putalpha(mask)
    
    # Overwrite the original file
    resized.save(filename, "PNG")

@app.post("/upload")
async def upload_file(file: UploadFile, username: Optional[str] = Depends(get_current_user)):
    try:
        # Ensure the upload directories exist
        upload_dir = os.path.join(os.getcwd(), "public", "pictures")
        os.makedirs(upload_dir, exist_ok=True)

        # Read the file content
        file_data = await file.read()
        
        # Generate unique filenames
        file_ext = os.path.splitext(file.filename)[1].lower()
        unique_id = str(uuid.uuid4())
        original_filename = f"{unique_id}_original{file_ext}"
        avatar_filename = f"{unique_id}_avatar.png"  # Always save as PNG
        
        # Paths for original and processed files
        original_path = os.path.join(upload_dir, original_filename)
        avatar_path = os.path.join(upload_dir, avatar_filename)

        # Save original file temporarily
        with open(original_path, "wb") as f:
            f.write(file_data)

        # Process into circular avatar
        try:
            with Image.open(original_path) as img:
                # Calculate largest possible circle
                width, height = img.size
                shorter_side = min(width, height)
                
                # Crop to square from center
                left = (width - shorter_side) / 2
                top = (height - shorter_side) / 2
                right = (width + shorter_side) / 2
                bottom = (height + shorter_side) / 2
                img = img.crop((left, top, right, bottom))
                
                # Convert to RGBA if needed
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Create circular mask
                mask = Image.new('L', (shorter_side, shorter_side), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, shorter_side, shorter_side), fill=255)
                
                # Apply mask
                result = Image.new('RGBA', (shorter_side, shorter_side))
                result.paste(img, (0, 0), mask)
                
                # Save the circular avatar
                result.save(avatar_path, format='PNG')
                resize_and_replace_circular_png(avatar_path, 600)
        except Exception as img_error:
            # Clean up if image processing fails
            os.remove(original_path)
            raise RuntimeError(f"Image processing failed: {str(img_error)}")

        # Delete the original file after processing
        os.remove(original_path)

        # Update database with avatar filename
        if username:
            skin_collection.update_one(
                {"username": username},
                {"$set": {"custom": avatar_filename}},
                upsert=True
            )

        print(f"Avatar successfully processed and saved to {avatar_path}")
        return {"file_path": f"pictures/{avatar_filename}"}

    except Exception as e:
        # Clean up any partial files if error occurs
        if 'original_path' in locals() and os.path.exists(original_path):
            os.remove(original_path)
        if 'avatar_path' in locals() and os.path.exists(avatar_path):
            os.remove(avatar_path)
            
        print(f"Error: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500) 

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
        loginReg_logger.info(credentials.username + " could not find username")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    salt = user.get("salt", "")
    if not verify_password(credentials.password, salt, user["hashed_password"]):
        loginReg_logger.info(credentials.username + " could not verify password")
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
    
    loginReg_logger.info(credentials.username + " login successful")
    return JSONResponse(content={"message": "Login successful"}, status_code=status.HTTP_200_OK, headers=response.headers)

@app.post("/api/register")
async def api_register(credentials: UserCredentials = Body(...)):
    """Handles user registration via API, expects JSON credentials."""
    
    if len(credentials.username) > 15:
        loginReg_logger.info(credentials.username + " tried to register with too long username")
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
            loginReg_logger.info(credentials.username + " tried to register with disallowed character " + char)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username contains invalid characters."
            )

    # Validate password complexity.
    if not check_password_complexity(credentials.password):
        loginReg_logger.info(credentials.username + " tried to register with bad password")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long and include at least three of: uppercase, lowercase, number, special character."
        )

    # Check if username already exists.
    if users_collection.find_one({"username": credentials.username}):
        loginReg_logger.info(credentials.username + " tried to register with username already in use")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, # Use 409 Conflict for existing resource
            detail="Username already registered"
        )

    salt, hashed_password = get_password_hash(credentials.password)

    users_collection.insert_one({
        "username": credentials.username,
        "salt": salt,
        "hashed_password": hashed_password,
        # --- Initialize Achievement Stats ---
        "total_score_lifetime": 0,
        "games_played": 0,
        "players_eaten_lifetime": 0,
        "unlocked_achievements": []
        # --- End Achievement Stats ---
    })

    new_stats = {
        "username": credentials.username,
        "gamesWon": 0,
        "deaths": 0,
        "kills": 0,
        "pellets": 0
    }
    playerStats_collection.insert_one(new_stats)

    loginReg_logger.info(credentials.username + " registration successful")
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

@app.get("/api/leaderboard")
async def get_leaderboard_data():
    """Retrieves the top 20 players based on total accumulated score."""
    try:
        top_players = list(
            leaderboard_stats_collection.find({}, {"_id": 0, "username": 1, "total_score": 1})
                                        .sort("total_score", -1)
                                        .limit(20)
        )
        return JSONResponse(content=top_players)
    except Exception as e:
        print(f"Error fetching leaderboard data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve leaderboard data."
        )

# --- Achievements API Endpoint ---
@app.get("/api/achievements")
async def get_user_achievements(username: str = Depends(get_current_user)):
    """Retrieves the status of all achievements for the logged-in user."""
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    print(f"[Achievements API] Attempting to find user: {username}") # Add logging
    user_data = users_collection.find_one({"username": username}, {"_id": 0, "unlocked_achievements": 1})
    print(f"[Achievements API] Result of find_one for {username}: {user_data}") # Add logging
    if user_data is None:
        # This shouldn't happen if the user is authenticated, but handle defensively
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User data not found."
        )
    unlocked_ids = set(user_data.get("unlocked_achievements", []))
    all_achievements_status = []
    for ach_id, details in ACHIEVEMENTS.items():
        all_achievements_status.append({
            "id": ach_id,
            "name": details["name"],
            "description": details["description"],
            "unlocked": ach_id in unlocked_ids
        })
    return JSONResponse(content=all_achievements_status)
# --- End Achievements API Endpoint ---

# --- Achievement Definitions ---
ACHIEVEMENTS = {
    # Score Achievements
    "score_30": {"name": "Point Novice", "description": "Reach a total lifetime score of 30 points.", "criteria": lambda stats: stats.get("total_score_lifetime", 0) >= 30},
    "score_60": {"name": "Point Adept", "description": "Reach a total lifetime score of 60 points.", "criteria": lambda stats: stats.get("total_score_lifetime", 0) >= 60},
    "score_90": {"name": "Point Master", "description": "Reach a total lifetime score of 90 points.", "criteria": lambda stats: stats.get("total_score_lifetime", 0) >= 90},
    # Games Played Achievements
    "played_1": {"name": "First Game!", "description": "Play your first game.", "criteria": lambda stats: stats.get("games_played", 0) >= 1},
    "played_5": {"name": "Getting Started", "description": "Play 5 games.", "criteria": lambda stats: stats.get("games_played", 0) >= 5},
    "played_10": {"name": "Regular Player", "description": "Play 10 games.", "criteria": lambda stats: stats.get("games_played", 0) >= 10},
    # Players Eaten Achievements
    "eaten_1": {"name": "First Bite", "description": "Eat your first player.", "criteria": lambda stats: stats.get("players_eaten_lifetime", 0) >= 1},
    "eaten_5": {"name": "Cannibal", "description": "Eat 5 players.", "criteria": lambda stats: stats.get("players_eaten_lifetime", 0) >= 5},
    "eaten_20": {"name": "Apex Predator", "description": "Eat 20 players.", "criteria": lambda stats: stats.get("players_eaten_lifetime", 0) >= 20},
}

# --- Achievement Helper Function ---
async def check_and_grant_achievements(username: str):
    """Checks and grants achievements based on LIFETIME stats (games played, eaten)."""
    if not username:
        return # Only logged-in users get achievements

    # Fetch only the stats needed for lifetime checks + unlocked list
    user_data = users_collection.find_one({"username": username}, {"_id": 0, "unlocked_achievements": 1, "games_played": 1, "players_eaten_lifetime": 1})
    if not user_data:
        print(f"[Achievements] User not found: {username}")
        return

    current_achievements = set(user_data.get("unlocked_achievements", []))
    newly_unlocked = []

    for achievement_id, details in ACHIEVEMENTS.items():
        # --- Skip score achievements, handled by check_in_game_score_achievements ---
        if achievement_id.startswith("score_"):
            continue
        # --- End Skip ---

        if achievement_id not in current_achievements:
            if details["criteria"](user_data): # Pass the whole user_data dict
                newly_unlocked.append(achievement_id)

    if newly_unlocked:
        print(f"[Achievements] User {username} unlocked: {newly_unlocked}")
        # Update database
        users_collection.update_one(
            {"username": username},
            {"$addToSet": {"unlocked_achievements": {"$each": newly_unlocked}}}
        )

        # Send notifications via WebSocket
        for client_id, client_info in clients.items():
            if client_info.get("username") == username:
                ws = client_info.get("ws")
                if ws:
                    for ach_id in newly_unlocked:
                        try:
                            await ws.send_json({
                                "type": "achievement_unlocked",
                                "achievement": {
                                    "id": ach_id,
                                    "name": ACHIEVEMENTS[ach_id]["name"],
                                    "description": ACHIEVEMENTS[ach_id]["description"]
                                }
                            })
                            print(f"[Achievements] Sent notification for {ach_id} to {username}")
                        except Exception as e:
                            print(f"[Achievements] Error sending notification to {username}: {e}")
                break

# --- New Helper for In-Game Score Achievements ---
async def check_in_game_score_achievements(username: str, current_power: int):
    """Checks and grants score achievements based on current in-game power."""
    if not username:
        return

    # Fetch only unlocked achievements to avoid duplicate checks/grants
    user_data = users_collection.find_one({"username": username}, {"_id": 0, "unlocked_achievements": 1})
    if user_data is None: # Check explicitly for None
        print(f"[AchievementsScore] User not found: {username}")
        return

    current_achievements = set(user_data.get("unlocked_achievements", []))
    newly_unlocked = []

    for achievement_id, details in ACHIEVEMENTS.items():
        # Only check score achievements
        if not achievement_id.startswith("score_"):
            continue

        if achievement_id not in current_achievements:
            # Evaluate criteria using current_power, passed as the expected stat name
            temp_stats = {"total_score_lifetime": current_power} # Simulate stats dict for lambda
            if details["criteria"](temp_stats):
                newly_unlocked.append(achievement_id)

    if newly_unlocked:
        print(f"[AchievementsScore] User {username} unlocked score achievements: {newly_unlocked} with power {current_power}")
        # Update database
        users_collection.update_one(
            {"username": username},
            {"$addToSet": {"unlocked_achievements": {"$each": newly_unlocked}}}
        )
        # Send notifications via WebSocket
        for client_id, client_info in clients.items():
            if client_info.get("username") == username:
                ws = client_info.get("ws")
                if ws:
                    for ach_id in newly_unlocked:
                        try:
                            await ws.send_json({
                                "type": "achievement_unlocked",
                                "achievement": {
                                    "id": ach_id,
                                    "name": ACHIEVEMENTS[ach_id]["name"],
                                    "description": ACHIEVEMENTS[ach_id]["description"]
                                }
                            })
                            print(f"[AchievementsScore] Sent notification for {ach_id} to {username}")
                        except Exception as e:
                            print(f"[AchievementsScore] Error sending notification to {username}: {e}")
                break
    
'''
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

'''
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

def recievedMove(jsonMessage: string):
    message = json.loads(jsonMessage)
    username = message["username"]
    player = player_dict.get(username)
    player.position_x = message["x"]
    player.position_y = message["y"]
    player_dict[username] = player

def add_player(jsonMessage: string):
    message = json.loads(jsonMessage)
    username = message["username"]
    player = Player(username)
    player_dict[username] = player #adds player to player dict

def add_food(jsonMessage: string): 
    message = json.loads(jsonMessage)
    foodId = message["foodId"]
    x = message["x"]
    y = message["y"]
    food = Food(foodId, x,y)
    food_dict[food.idd] = food

def get_leaderboard():
    pass

def initial(jsonMessage : string):
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

def GetsPositionsJson():
    dict1 = {"type":"update"} #{"type":"update","players":[{"username":str,"x":int,"y":int,"size":int}....]}
    players = []
    for player in player_dict.values():
        dict2 = {"username":player.username,"x":player.position_x,"y":player.position_y, "size":player.size}
        players.append(dict2)
    dict1["players"] = players
    jUpdate = json.dumps(dict1)
    return jUpdate

def ate_food(jsonMessage: string):
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

def winner(player1, player2):
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

def remove_buff_debuff(player : Player, buff : string): 
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
 