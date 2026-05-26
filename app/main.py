from fastapi import FastAPI
from app.db.supabase import is_supabase_connected

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Inbox Orchestrator Server is running"}


@app.get("/health")
async def get_health():
    ok = is_supabase_connected()
    return {"supabase": "OK" if ok else "FAILED"}
