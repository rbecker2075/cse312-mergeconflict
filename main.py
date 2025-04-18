import os
from fastapi.responses import FileResponse
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

app = FastAPI(title='test',
              description='testing desc',
              version='1.0')

app.mount("/", StaticFiles(directory="public", html=True), name="static")

INDEX_FILE_PATH = os.path.join("public", "index.html")
@app.get("/")
async def root():
    return FileResponse(INDEX_FILE_PATH)


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
