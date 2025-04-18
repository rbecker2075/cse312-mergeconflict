from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pymongo import MongoClient
import os

app = FastAPI()

# MongoDB setup
client = MongoClient(os.environ["MONGO_URL"])
db = client.test_database

# Mount static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve HTML page at root
@app.get("/")
async def serve_homepage():
    return FileResponse("static/echo.html")

# REST endpoints
@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

@app.get("/data")
def get_data():
    return {"collections": db.list_collection_names()}

# WebSocket Echo Endpoint
@app.websocket("/ws/echo")
async def websocket_echo(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        print("Client disconnected")