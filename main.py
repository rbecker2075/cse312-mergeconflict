import uvicorn
import asyncio
import json
from fastapi import FastAPI, Request, Depends, HTTPException, status, Response, Cookie, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from database import users_collection, sessions_collection
from typing import Optional
import os
import string
from auth import get_password_hash, verify_password, create_access_token, hash_token, get_current_user
from pydantic import BaseModel # Added for request bodies
import datetime
import random
import time
import asyncio
from uuid import uuid4
from random import choice
app = FastAPI(title='Merge Conflict Game', description='Authentication and Game API', version='1.0')

# Mount 'public/imgs' directory to serve images under '/imgs' path
app.mount("/imgs", StaticFiles(directory="public/Imgs"), name="imgs")

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


# --- Routes for Serving Frontend Pages ---

clients = {}

# Add these at the top with other global variables
game_start_time = None
game_duration = 300  # 5 minutes in seconds
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

@app.websocket("/ws/game")
async def game_ws(websocket: WebSocket):
    global game_start_time, food_instances
    
    # Start the game timer if this is the first connection
    if game_start_time is None and len(clients) == 0:
        game_start_time = time.time()
        generate_food()  # Generate initial food
    
    await websocket.accept()
    player_id = str(uuid4())
    
    # Get the session token from cookies
    session_token = websocket.cookies.get("session_token")
    username = None
    if session_token:
        username = await get_current_user(session_token)
    
    clients[player_id] = {"ws": websocket, "x": 0, "y": 0, "power": 1, "username": username}

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
                winner = max(clients.items(), key=lambda x: x[1]["power"])
                winner_username = winner[1]["username"] or "Guest"
                
                # Send game over message to all clients
                for client in clients.values():
                    try:
                        await client["ws"].send_json({
                            "type": "game_over",
                            "winner": winner_username
                        })
                    except:
                        pass
                
                # Wait for 5 seconds before resetting
                await asyncio.sleep(5)
                
                # Reset game state
                game_start_time = time.time()  # Reset timer
                generate_food()  # Generate new food
                for client_id in clients:
                    clients[client_id]["power"] = 1  # Reset all powers to 1
                    clients[client_id]["x"] = random.randint(0, worldWidth)  # Random respawn
                    clients[client_id]["y"] = random.randint(0, worldHeight)
                
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
            
            # Remove collected food and notify all clients
            if food_to_remove:
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
            for pid, client in clients.items():
                if pid != player_id:
                    distance = ((clients[player_id]["x"] - client["x"]) ** 2 + (clients[player_id]["y"] - client["y"]) ** 2) ** 0.5
                    if distance < 75:  # Increased from 50 to 75 for player collision radius
                        # Collision: Compare powers
                        if clients[player_id]["power"] > client["power"]:
                            # Only increase power if loser is not at power 1
                            if client["power"] > 1:
                                clients[player_id]["power"] += client["power"]
                                clients[player_id]["power"] -= 1
                            client["power"] = 1
                        elif clients[player_id]["power"] < client["power"]:
                            # Only increase power if loser is not at power 1
                            if clients[player_id]["power"] > 1:
                                client["power"] += clients[player_id]["power"]
                                client["power"] -= 1
                            clients[player_id]["power"] = 1
                        else:
                            # Tie case: Randomly choose a winner
                            winner = choice([player_id, pid])
                            if winner == player_id:
                                clients[player_id]["power"] += client["power"]
                                if clients[player_id]["power"] > 2:
                                    clients[player_id]["power"] -= 1
                                client["power"] = 1
                            else:
                                client["power"] += clients[player_id]["power"]
                                if client["power"] > 2:
                                    client["power"] -= 1
                                clients[player_id]["power"] = 1

            # Prepare data for all players
            state = {
                "type": "players",
                "players": {
                    pid: {"x": info["x"], "y": info["y"], "power": info["power"], "username": info["username"]}
                    for pid, info in clients.items()
                    if "x" in info and "y" in info
                },
                "time_remaining": time_remaining,
                "food": food_instances
            }
            for pid, client in clients.items():
                try:
                    await client["ws"].send_json(state)
                except WebSocketDisconnect:
                    print(f"Client {pid} disconnected")

    except WebSocketDisconnect:
        # Player disconnecting logic
        del clients[player_id]
        # If no players left, stop the timer
        if len(clients) == 0:
            game_start_time = None
        # Broadcast removal only to other clients
        for other_pid, client in clients.items():
            try:
                await client["ws"].send_json({"type": "remove", "id": player_id})
            except:
                pass


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




def request_log(request : Request, response : Response ):
   tim = datetime.datetime.now()
   content ="time: "+ tim.strftime("%m/%d/%Y, %H:%M:%S") + "\n client " + str(request.client.host)+"\n method " + str(request.method) + "\n url path " + str(request.url.path) + '\n response code ' + str(response.status_code) +"\n\n"
   with open("public/logs/request_logs.txt", "a") as f:
        f.write(content)

def fullLogging(request : Request, response : Response ):
    req = b""
    reqS = request.method + request.url.path
    for header in request.headers:
        reqS = reqS + header +": "+ request.headers[header]# need to take out auth tokens and handle cookies better
    req = reqS.encode() + b"\n"
    res = b""
    with open("./logs/fullreq.txt","ab") as f:
        f.write(req)
    with open("./logs/fullres.txt","ab") as f:
        f.write(res)

#to do docker logs, volume
def errorLog(error : string, tb : string):
    content = "error: " + error + "\n" + tb
    with open("./logs/error_log.txt","b") as f:
        f.write(content)

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
# --- Remove duplicate /login route and /hello/{name} ---

# --- Add main execution block (optional, for running directly) ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

player_dict = {}# I assume we will update this when we get/lose players #assuming {username:player}
class Player:
    def __init__(self, username):
        self.username = username #these are stand in numbers if you want to change them
        position_x : int #these I assume will be randomly generated and set after
        position_y : int
        self.size = 20
        self.speed = 5
        self.debuffs = {"debuff_speed":False,"debuff_size":False }#assuming maybe 2 debuffs and 2 buffs, increase and decrease size and speed temp
        self.buffs = {"buff_speed":False,"buff_size":False }

def winner(player1, player2):#returns dict with winner and loser
    if player1.size > player2.size:
        player1.size += player2.size #player 1 gets player 2 size
        speed_update(player1) #updates player 1 speed
        player_dict[player1.username] = player1
        del player_dict[player2.username]  # player 2 loses and is deleted from player_dict
        return {"loser":player2,"winner":player1} #return player2 to broadcast defeat?
    elif player1.size < player2.size:
        player2.size += player1.size  # player 1 gets player 2 size
        speed_update(player2)
        player_dict[player2.username] = player2
        del player_dict[player1.username]
        return {"loser":player1, "winner":player2}
    else:
        p = random.choice([player1, player2])
        if p.username == player1.username:#player 1 is decided winner
            player1.size += player2.size #increase player 1 by player2 size
            speed_update(player1) #update speed
            player_dict[player1.username] = player1
            del player_dict[player2.username]  # del player 2
            return {"loser":player2,"winner":player1} #return player2 to broadcast defeat?
        else:#player 2 is decided winner
            player2.size += player1.size
            speed_update(player2)
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

def ate_food(player):
    player.size += 1
    player = speed_update(player)
    return player
