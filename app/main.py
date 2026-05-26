from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Inbox Orchestrator Server is running"}


@app.get("/health")
async def get_health():
    return {"message": "OK"}
