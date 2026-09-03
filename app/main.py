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
from app.api.analytics_router import router as analytics_router
from app.api.calendar_router import router as calendar_router
from app.api.settings_router import router as settings_router

app = FastAPI(title="InboxOrchestrator AI Engine")
raw_frontend_urls = os.getenv("FRONTEND_URL", "http://localhost:3000")
allowed_origins = [url.strip() for url in raw_frontend_urls.split(",") if url.strip()]
cors_regex = os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=cors_regex if cors_regex else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, tags=["auth"])
# Mount specific domain sub-routers BEFORE wildcard email_router to avoid route shadowing
app.include_router(thread_router)
app.include_router(draft_router)
app.include_router(task_router)
app.include_router(calendar_router)
app.include_router(search_router)
app.include_router(analytics_router)
app.include_router(settings_router)
app.include_router(email_router)
register_exception_handlers(app)


@app.get("/")
async def root():
    return {"message": "Inbox Orchestrator Server is running"}


@app.get("/health")
async def get_health():
    ok = is_supabase_connected()
    return {
        "status": "ok" if ok else "degraded",
        "supabase": "OK" if ok else "FAILED",
        "service": "InboxOrchestrator AI Engine"
    }
