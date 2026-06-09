from fastapi import FastAPI
from app.db.supabase import is_supabase_connected

from app.api.app_exceptions import register_exception_handlers
from app.api.auth_router import router as auth_router

app = FastAPI(title="InboxOrchestrator AI Engine")
app.include_router(auth_router, tags=["auth"])
register_exception_handlers(app)

@app.get("/")
async def root():
    return {"message": "Inbox Orchestrator Server is running"}


@app.get("/health")
async def get_health():
    ok = is_supabase_connected()
    return {"supabase": "OK" if ok else "FAILED"}
