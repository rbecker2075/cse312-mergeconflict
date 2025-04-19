import os
import uuid


from fastapi.responses import FileResponse
from fastapi import FastAPI, Request, Response
from starlette.staticfiles import StaticFiles

app = FastAPI(title='test',
              description='testing desc',
              version='1.0')

app.mount("/", StaticFiles(directory="public", html=True), name="static")
app.mount("/imgs", StaticFiles(directory="public/imgs"), name="imgs")

INDEX_FILE_PATH = os.path.join("public", "index.html")
@app.get("/")
async def root(response: Response, request: Request):

    session_cookie = request.cookies.get("session") is not None

    if not session_cookie:
        # Generate a new session ID
        new_session_id = str(uuid.uuid4())
        # Set the session cookie
        response.set_cookie(key="session", value=new_session_id, httponly=True, samesite="Lax")

    return FileResponse(INDEX_FILE_PATH)




@app.get("/auth/status")
async def auth_status(request: Request):
    # Check user authentication status (this is just an example)
    # Replace with your actual authentication logic

    if request.cookies.get("auth_token") is not None:
        logged_in = request.cookies.get("auth_token")
    else:
        logged_in = None
    return {"logged_in": logged_in}