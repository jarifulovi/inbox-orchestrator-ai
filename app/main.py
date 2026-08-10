import os

from fastapi import FastAPI
from app.core.db.supabase import is_supabase_connected
from fastapi.middleware.cors import CORSMiddleware
from app.api.app_exceptions import register_exception_handlers
from app.api.auth_router import router as auth_router
from app.api.email_router import router as email_router
from app.api.thread_router import router as thread_router
from app.api.task_router import router as task_router
from app.api.search_router import router as search_router
from app.api.draft_router import router as draft_router

app = FastAPI(title="InboxOrchestrator AI Engine")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, tags=["auth"])
# Mount specific domain sub-routers BEFORE wildcard email_router to avoid route shadowing
app.include_router(thread_router)
app.include_router(draft_router)
app.include_router(task_router)
app.include_router(search_router)
app.include_router(email_router)
register_exception_handlers(app)


@app.get("/")
async def root():
    return {"message": "Inbox Orchestrator Server is running"}


@app.get("/health")
async def get_health():
    ok = is_supabase_connected()
    return {"supabase": "OK" if ok else "FAILED"}
