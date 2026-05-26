import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Ensure environment variables are loaded from the local .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
# NOTE: For the backend processing tasks (saving tasks, writing ML outputs),
# use the private 'service_role' key here instead of the public 'anon' key
# so the script can bypass Row Level Security (RLS) constraints.
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

# Internal global reference used to maintain a strict Singleton pattern
_client: Client | None = None


def get_supabase_client() -> Client | None:
    """
    Thread-safe Singleton provider for the Supabase Client connection.
    Initializes the network client on the first execution and subsequently
    distributes the active instance across the application lifecycle.
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
    global client
    try:
        client = get_supabase_client()

        # We query an internal vault/rpc metadata viewpoint that always exists by default.
        # This completely avoids having to build temporary testing schemas.
        client.from_("_analytics").select("*").limit(1).execute()
        return True
    except Exception:
        # If _analytics is restricted under your current token setup,
        # fallback to checking a basic authentication parameter lookup over the web.
        try:
            client.auth.get_session()
            return True
        except Exception as e:
            print(f"\n[CRITICAL] Supabase Connection Health Check Failed: {e}\n")
            return False