from fastapi import Depends, Header, HTTPException
from app.db.supabase import get_supabase_client
from app.web_services.auth_web_service import AuthWebService


def get_current_user(
    authorization: str = Header(None),
    db = Depends(get_supabase_client)
):
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing token")

        token = authorization.replace("Bearer ", "")

        service = AuthWebService(db_client=db)
        return service.verify_jwt(token)

    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))