import os
import time
from dotenv import load_dotenv
from supabase import create_client, Client
import httpx

# Ensure environment variables are loaded from the local .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

# Internal global reference used to maintain a Singleton pattern
_client: Client | None = None


def get_supabase_client(force_new: bool = False) -> Client:
    """
    Singleton provider for the Supabase Client connection.
    Initializes the network client on the first execution or forces a fresh client if requested.
    """
    global _client
    if force_new or _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "Critical Configuration Failure: SUPABASE_URL or SUPABASE_KEY "
                "is missing from the environment variables."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def reset_supabase_client() -> Client:
    """Resets the singleton client and creates a fresh instance to clear stale HTTP/2 connection pools."""
    global _client
    _client = None
    return get_supabase_client(force_new=True)


# Centrally patch PostgREST's sync request execution to recover from stale HTTP/2 pool terminations across the entire app
try:
    import postgrest._sync.request_builder as _postgrest_sync_builder
    from httpx import Headers

    _orig_send_with_retry = _postgrest_sync_builder.send_with_retry

    def _resilient_send_with_retry(req):
        attempt_count = 0
        while True:
            headers = (
                Headers({"X-Retry-Count": str(attempt_count)})
                if attempt_count > 0
                else Headers()
            )
            try:
                resp = req.send(headers)
            except Exception as e:
                err_str = str(e)
                if attempt_count < 2 and any(k in err_str for k in ("ConnectionTerminated", "RemoteProtocolError", "httpcore", "closed", "Pool")):
                    print(f"[SUPABASE AUTO-RECONNECT] Stale HTTP connection pool detected ({err_str}). Re-initializing client...")
                    reset_supabase_client()
                    fresh_client = get_supabase_client()
                    if hasattr(fresh_client, "postgrest") and hasattr(fresh_client.postgrest, "_session"):
                        req.session = fresh_client.postgrest._session
                    time.sleep(0.1)
                    attempt_count += 1
                    continue
                raise e

            if resp.is_success or not req.should_retry(resp, attempt_count=attempt_count):
                break
            time.sleep(_postgrest_sync_builder.get_retry_delay(resp, attempt_count))
            attempt_count += 1
        return resp

    _postgrest_sync_builder.send_with_retry = _resilient_send_with_retry
    print("[SUPABASE DB] Central HTTP/2 Auto-Reconnect handler registered successfully.")
except Exception as patch_err:
    print(f"[SUPABASE DB WARNING] Failed to patch PostgREST retry handler: {patch_err}")


def is_supabase_connected() -> bool:
    """
    Performs a real, minimal network request to verify live connectivity
    and valid credentials against the remote Supabase API engine.
    """
    try:
        active_client = get_supabase_client()
        active_client.from_("_analytics").select("*").limit(1).execute()
        return True
    except Exception:
        try:
            active_client = get_supabase_client()
            active_client.auth.get_session()
            return True
        except Exception as e:
            print(f"\n[CRITICAL] Supabase Connection Health Check Failed: {e}\n")
            return False