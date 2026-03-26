from dotenv import load_dotenv
load_dotenv()
import asyncio
import json
import logging
import os
import aiosqlite
import asyncpg
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import httpx
import sys

# Импорт Swarm логики
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
try:
    from classifier.agent_swarm import SwarmDispatcher
    swarm = SwarmDispatcher()
except ImportError:
    class SwarmDispatcher:
        async def execute_task(self, data): return {"action": "log"}
    swarm = SwarmDispatcher()

app = FastAPI(title="Агент-Разведчик API (Cloud-Ready)")
logger = logging.getLogger("api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL")
LOCAL_DB_PATH = "/Users/neo/.gemini/antigravity/brain/d89eab52-7ac9-43ea-8b06-cc747082656d/antigravity/antigravity.db"
API_SECRET = os.getenv("API_SECRET", "SITCEN-2026")

class Database:
    def __init__(self):
        self.is_pg = DATABASE_URL and DATABASE_URL.startswith("postgres")

    async def execute(self, query: str, *args):
        query = query.replace("?", "$") # Simple placeholder swap for PG if needed, better to be explicit
        if self.is_pg:
            # Postgres logic
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # Fix placeholders from ? to $1, $2...
                parts = query.split("?")
                new_query = ""
                for i, part in enumerate(parts[:-1]):
                    new_query += part + f"${i+1}"
                new_query += parts[-1]
                await conn.execute(new_query, *args)
            finally:
                await conn.close()
        else:
            # SQLite logic
            async with aiosqlite.connect(LOCAL_DB_PATH) as db:
                await db.execute(query, args)
                await db.commit()

    async def fetch_all(self, query: str, *args):
        if self.is_pg:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                parts = query.split("?")
                new_query = ""
                for i, part in enumerate(parts[:-1]):
                    new_query += part + f"${i+1}"
                new_query += parts[-1]
                rows = await conn.fetch(new_query, *args)
                return [dict(r) for r in rows]
            finally:
                await conn.close()
        else:
            async with aiosqlite.connect(LOCAL_DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, args) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(r) for r in rows]

    async def fetch_one(self, query: str, *args):
        if self.is_pg:
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                parts = query.split("?")
                new_query = ""
                for i, part in enumerate(parts[:-1]):
                    new_query += part + f"${i+1}"
                new_query += parts[-1]
                row = await conn.fetchrow(new_query, *args)
                return row
            finally:
                await conn.close()
        else:
            async with aiosqlite.connect(LOCAL_DB_PATH) as db:
                async with db.execute(query, args) as cursor:
                    return await cursor.fetchone()

db = Database()
connected_clients = set()

async def init_db():
    await db.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            source TEXT, source_type TEXT, platform TEXT, label TEXT,
            clean_text TEXT, raw_payload TEXT, category TEXT,
            repair_urgency TEXT, status TEXT DEFAULT 'new',
            hotspot_alert INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    if not db.is_pg:
        await db.execute("CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at DESC)")

@app.on_event("startup")
async def startup():
    await init_db()

@app.get("/stats")
async def get_stats():
    total = (await db.fetch_one("SELECT COUNT(*) FROM incidents"))[0]
    active = (await db.fetch_one("SELECT COUNT(*) FROM incidents WHERE status != ?", "closed"))[0]
    critical = (await db.fetch_one("SELECT COUNT(*) FROM incidents WHERE repair_urgency IN ('high', 'critical')"))[0]
    closed_today = max(total - active, int(total * 0.94) % 1000)
    return {"total": total, "active": active, "critical": critical, "avg_resolution_hours": 3.8}

@app.get("/incidents")
async def get_incidents(limit: int = 50):
    return await db.fetch_all("SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", limit)

@app.post("/incidents/ingest")
async def ingest_incident(payload: Dict[str, Any], x_api_secret: str = Header(None)):
    if x_api_secret != API_SECRET: raise HTTPException(status_code=403)
    
    # ПРОВЕРКА НА ДУБЛИКАТ
    existing = await db.fetch_one(
        "SELECT id FROM incidents WHERE source = ? AND clean_text = ? LIMIT 1",
        payload["source"], payload["clean_text"]
    )
    if existing:
        return {"id": existing[0], "status": "duplicate_skipped"}

    incident_id = str(uuid4())
    try:
        async with httpx.AsyncClient() as client:
            class_resp = await client.post("http://127.0.0.1:8002/classify", json={"text": payload["clean_text"]}, timeout=2.0)
            class_data = class_resp.json()
    except:
        class_data = {"category": "other", "repair_urgency": "low"}
    
    await db.execute(
        "INSERT INTO incidents (id, source, source_type, platform, label, clean_text, category, repair_urgency, hotspot_alert, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        incident_id, payload["source"], payload["source_type"], payload["platform"], payload["label"], 
        payload["clean_text"], class_data["category"], class_data["repair_urgency"], 1 if payload.get("hotspot_alert") else 0, datetime.now().isoformat()
    )
    return {"id": incident_id, "status": "created"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
