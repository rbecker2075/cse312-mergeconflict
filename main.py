from fastapi import FastAPI
from pymongo import MongoClient
import os

app = FastAPI()

client = MongoClient(os.environ["MONGO_URL"])
db = client.test_database


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

@app.get("/data")
def get_data():
    return {"collections": db.list_collection_names()}
