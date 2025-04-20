import os
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

app = FastAPI(title='test', description='testing desc', version='1.0')

# Mount static files for public directory
app.mount("/", StaticFiles(directory="public", html=True), name="static")

# Ensure this path exists
INDEX_FILE_PATH = "public/index.html"
LOGIN_PAGE_PATH = os.path.join("public", "login_page")  # Set the correct path to your login page

@app.get("/")
async def root(response: Response, request: Request):
    session_cookie = request.cookies.get("session") is not None

    if not session_cookie:
        # Generate a new session ID
        new_session_id = str(uuid.uuid4())
        # Set the session cookie
        response.set_cookie(key="session", value=new_session_id, httponly=True, samesite="Lax")

    return FileResponse(INDEX_FILE_PATH)
@app.get('/register')
async def root(response: Response, request: Request):

    return FileResponse('public/register.html')



@app.get('/login')  # Ensure this route is correctly defined with a leading slash
async def login(response: Response, request: Request):
    return FileResponse(INDEX_FILE_PATH)

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}