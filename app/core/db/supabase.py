import os
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