import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "office_monitor"
COLLECTION_NAME = "movemeon_projects"

def init_mongo():
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        
        # Collections are created automatically, but we'll ensure it exists and create the index
        if COLLECTION_NAME not in db.list_collection_names():
            print(f"Creating collection: {COLLECTION_NAME}")
            db.create_collection(COLLECTION_NAME)
        
        print(f"Ensuring index on project_id for {COLLECTION_NAME}")
        db[COLLECTION_NAME].create_index("project_id", unique=True)
        print("MongoDB initialization successful.")
        client.close()
    except Exception as e:
        print(f"MongoDB initialization failed: {e}")

if __name__ == "__main__":
    init_mongo()
