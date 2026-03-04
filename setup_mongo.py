"""
One-time setup: creates the catalant_projects collection with
schema validation and indexes in MongoDB Atlas.
Run once: python setup_mongo.py
"""
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv
import os

load_dotenv()

uri = os.getenv("MONGO_URI")
if not uri:
    raise SystemExit("❌ MONGO_URI not set in .env")

client = MongoClient(uri, serverSelectionTimeoutMS=8000)
db = client["office_monitor"]

# ── Drop + recreate to apply latest schema ──────────────────────────────────
if "catalant_projects" in db.list_collection_names():
    db["catalant_projects"].drop()
    print("🗑️  Dropped existing 'catalant_projects' collection")

db.create_collection(
    "catalant_projects",
    validator={
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["id", "title", "platform"],
            "properties": {
                # ── identity ───────────────────────────────────────────
                "id": {
                    "bsonType": "string",
                    "description": "Unique Catalant project slug/ID (required)"
                },
                "platform": {
                    "bsonType": "string",
                    "enum": ["catalant"],
                    "description": "Always 'catalant'"
                },
                # ── job details ────────────────────────────────────────
                "title": {
                    "bsonType": "string",
                    "description": "Job title (required)"
                },
                "location": {
                    "bsonType": "string",
                    "description": "Location or 'Remote'"
                },
                "duration": {
                    "bsonType": "string",
                    "description": "Project length / engagement duration"
                },
                "budget": {
                    "bsonType": "string",
                    "description": "Budget or rate range"
                },
                "status": {
                    "bsonType": "string",
                    "description": "e.g. Posted, New Project"
                },
                "url": {
                    "bsonType": "string",
                    "description": "Direct link to the project page"
                },
                # ── timing ─────────────────────────────────────────────
                "time_posted": {
                    "bsonType": "string",
                    "description": "Human-readable posting age from the listing"
                },
                "detected_at": {
                    "bsonType": "string",
                    "description": "Timestamp when the scraper first saw this job (YYYY-MM-DD HH:MM:SS)"
                },
                # ── notification flag ──────────────────────────────────
                "emailed": {
                    "bsonType": "bool",
                    "description": "true = email alert sent, false = silently seeded on cold start"
                },
            }
        }
    },
)
print("✅ Collection 'catalant_projects' created with schema validator")

col = db["catalant_projects"]

# ── Indexes ─────────────────────────────────────────────────────────────────
col.create_index([("id", ASCENDING)], unique=True, name="idx_id_unique")
print("✅ Unique index on 'id' ready")

col.create_index([("platform", ASCENDING), ("emailed", ASCENDING)], name="idx_platform_emailed")
print("✅ Compound index on 'platform + emailed' ready")

col.create_index([("detected_at", ASCENDING)], name="idx_detected_at")
print("✅ Index on 'detected_at' ready")

col.create_index([("time_posted", ASCENDING)], name="idx_time_posted")
print("✅ Index on 'time_posted' ready")

# ── Summary ──────────────────────────────────────────────────────────────────
print()
print("📋 Collection schema — fields:")
fields = [
    ("id",           "Unique project ID/slug"),
    ("title",        "Job title"),
    ("location",     "Location / Remote"),
    ("duration",     "Project length"),
    ("budget",       "Budget / rate"),
    ("status",       "Posted / New Project"),
    ("url",          "Direct link to project"),
    ("time_posted",  "Time posted (from listing)"),
    ("detected_at",  "Time scraped (by monitor)"),
    ("emailed",      "Email sent? true / false"),
    ("platform",     "Always 'catalant'"),
]
for name, desc in fields:
    print(f"   {name:<15} — {desc}")

print()
print("🎉 Catalant Monitor collection is ready in Atlas.")
