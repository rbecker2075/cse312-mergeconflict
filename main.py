import os
from fastapi.responses import FileResponse
from fastapi import FastAPI, Request
from starlette.staticfiles import StaticFiles

app = FastAPI(title='test',
              description='testing desc',
              version='1.0')

app.mount("/", StaticFiles(directory="public", html=True), name="static")

INDEX_FILE_PATH = os.path.join("public", "index.html")
@app.get("/")
async def root():
    return FileResponse(INDEX_FILE_PATH)




@app.get("/auth/status")
async def auth_status(request: Request):
    # Check user authentication status (this is just an example)
    # Replace with your actual authentication logic
    logged_in = request.cookies.get("session_token") is not None
    logged_in = request.cookies.get("auth_token") is not None

    return {"logged_in": logged_in}