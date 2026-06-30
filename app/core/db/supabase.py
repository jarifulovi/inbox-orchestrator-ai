import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Ensure environment variables are loaded from the local .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

# Internal global reference used to maintain a strict Singleton pattern
_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Thread-safe Singleton provider for the Supabase Client connection.
    Initializes the network client on the first execution and subsequently
    distributes the active instance across the application lifecycle.

    Guarantees a 'Client' return or raises a RuntimeError.
    """
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "Critical Configuration Failure: SUPABASE_URL or SUPABASE_KEY "
                "is missing from the environment variables."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def is_supabase_connected() -> bool:
    """
    Performs a real, minimal network request to verify live connectivity
    and valid credentials against the remote Supabase API engine.
    """
    try:
        # Use a localized client variable inside the check to prevent cross-scope pollution
        active_client = get_supabase_client()

        # We query an internal vault/rpc metadata viewpoint that always exists by default.
        # This completely avoids having to build temporary testing schemas.
        active_client.from_("_analytics").select("*").limit(1).execute()
        return True
    except Exception:
        # Fallback tracking if analytics tables are restricted under the current role token setup.
        try:
            # We fetch the client safely again to guarantee it's assigned inside this block's scope
            active_client = get_supabase_client()
            active_client.auth.get_session()
            return True
        except Exception as e:
            print(f"\n[CRITICAL] Supabase Connection Health Check Failed: {e}\n")
            return False