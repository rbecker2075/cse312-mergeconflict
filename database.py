from pymongo import MongoClient
import os

mongo_url = os.environ["MONGO_URL"]
print(f"Connecting to MongoDB at: {mongo_url}")
try:
    client = MongoClient(mongo_url)
    client.admin.command('ismaster')
    print("MongoDB connection successful.")
except Exception as e:
    print(f"ERROR: Could not connect to MongoDB at {mongo_url}")
    print(e)
    raise

db = client.app_database
users_collection = db.users
sessions_collection = db.sessions
leaderboard_stats_collection = db.leaderboard_stats

print("Database collections initialized.")