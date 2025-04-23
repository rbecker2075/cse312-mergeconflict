from pymongo import MongoClient
import os

# Database connection
client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = client.app_database
users_collection = db.users
sessions_collection = db.sessions
pellet_collection = db.pellet