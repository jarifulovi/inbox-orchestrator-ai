# test_ml_pipeline.py
import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client
from uuid import UUID

# Import your core orchestrator engine
from app.core.services.ml_service import MLEngineService
from app.models.action_extractor.components.processors import TextPreprocessor
from app.models.classifier.preprocessor import EmailPreprocessor


def run_pipeline_integration_test(email_limit: int = 2):
    print("=" * 70)
    print("[TEST INITIALIZATION] Loading local environment configs...")
    print("=" * 70)

    # 1. Load Environment Pointers
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_service_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_service_key:
        print("[CRITICAL ERROR] Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env file.")
        return

    # 2. Instantiate Admin Supabase Client (RLS Bypass)
    print("[SUPABASE] Connecting via Admin Service Role...")
    supabase: Client = create_client(supabase_url, supabase_service_key)

    # 3. Pull Real Email Safe Chunks from Database
    print("[DATABASE] Querying a sample batch of real emails...")
    try:
        # Adjust table name 'emails' if your DB uses a different naming schema
        response = supabase.table("emails").select("*").limit(email_limit).execute()
        raw_emails = response.data
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to fetch target rows: {e}")
        return

    if not raw_emails:
        print("[WARNING] Zero records returned from the database. Insert raw data first.")
        return

    print(f"[DATABASE] Successfully loaded {len(raw_emails)} email records for testing.")

    # 4. Initialize Your ML Service Engine
    print("[ML SERVICE] Warming up pipeline model components...")
    ml_service = MLEngineService()

    # 5. Execute the End-to-End Core Pipeline
    print("\n" + "=" * 70)
    print("[PIPELINE RUN] Executing run_batch_inference over data records...")
    print("=" * 70)

    try:
        # Running the execution loop exactly how your app expects it
        batch_results = ml_service.run_batch_inference(
            email_nodes=raw_emails,
            historical_context=[]  # Passing empty list for phase 1 historical baseline
        )
    except Exception as e:
        print(f"[PIPELINE CRASH] Loop execution failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 6. Verify and Inspect Output Payloads
    print("\n" + "=" * 70)
    print("[TEST RESULT ANALYSIS] Output Schema Struct Verification:")
    print("=" * 70)

    for i, payload in enumerate(batch_results):
        original_email = raw_emails[i]
        email_body = original_email.get("body") or original_email.get("content") or "No body content found"

        print(f"\n--- [RECORD #{i + 1}] Email ID: {payload.get('id')} ---")
        print(f"Master Table Status Code: {payload.get('status')}")

        # Print the actual text being evaluated
        print(f"\n[Raw Email Body Evaluated]:\n{email_body}")
        print("-" * 40)

        print("\n[Pass 2a: Intent Classification]")
        print(json.dumps(to_serializable_dict(payload.get("classification")), indent=4))

        print("\n[Pass 2b: Action Extractor Response]")
        print(json.dumps(to_serializable_dict(payload.get("actions")), indent=4))

        print("\n[Pass 2c: Post-Security Metric Core]")
        print(json.dumps(to_serializable_dict(payload.get("security")), indent=4))

    print("\n" + "=" * 70)
    print("[TEST COMPLETED] Run script completely executed.")
    print("=" * 70)


def to_serializable_dict(data) -> dict | list | str | int | float | bool:
    """Recursively converts Pydantic models, class instances, and UUIDs into standard JSON-safe structures."""
    if data is None:
        return {}

    # 1. Extract raw dictionary from Pydantic models first, but DO NOT return immediately.
    # We pass it down to let the dictionary parser recursively handle nested UUIDs or objects.
    if hasattr(data, "model_dump"):  # Pydantic v2
        data = data.model_dump()
    elif hasattr(data, "dict"):  # Pydantic v1
        data = data.dict()
    elif hasattr(data, "__dict__"):  # Standard Python object
        data = data.__dict__

    # 2. Convert UUID instances directly into standard string format
    if isinstance(data, UUID):
        return str(data)

    # 3. Recursively deep-clean lists
    if isinstance(data, list):
        return [to_serializable_dict(item) for item in data]

    # 4. Recursively deep-clean dictionaries (catches keys/values inside Pydantic dumps)
    if isinstance(data, dict):
        return {k: to_serializable_dict(v) for k, v in data.items()}

    return data


def test_single_text_payload():
    print("=" * 70)
    print("[MOCK RUN] Initializing Synchronous Pipeline Test...")
    print("=" * 70)

    # 1. FIXED SCHEMA MATCHING: Reflects real webhook matrix structures
    mock_email_nodes = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "subject": "Urgent: Project Sync and Contract Review",
            "raw_payload": {
                "headers": {
                    "Subject": "Urgent: Project Sync and Contract Review"
                }
            },
            "body": (
                "Hi team, let's look at the quarterly targets.\n"
                "++++\n"  # Test case 1: Plus line
                "Please confirm your availability for our technical sync tomorrow morning.\n"
                "I need you to verify the deployment metrics before we hop on the call.\n\n"
                "****\n"  # Test case 2: Asterisk line
                "Review the updated contract framework on our shared portal: "
                "[https://internal-workspace.supabase.co/projects/v1/review?token=f69c0d987a545032aacf9b5b425e5892d7488c14f680f4952c4cad4d&redirect_to=dashboard](https://internal-workspace.supabase.co/projects/v1/review?token=f69c0d987a545032aacf9b5b425e5892d7488c14f680f4952c4cad4d&redirect_to=dashboard)\n\n"
                "---------------------\n"  # Test case 3: Dash line
                "Thanks,\n"
                "Operations Management"
            )
        }
    ]

    # 2. Fire up the service engine
    ml_service = MLEngineService()

    # 3. Process the inference sequentially (Synchronous)
    try:
        print("\nExecuting run_batch_inference over mock node...")
        batch_results = ml_service.run_batch_inference(
            email_nodes=mock_email_nodes,
            historical_context=[]
        )
    except Exception as e:
        print(f"[CRASH DETECTED] Pipeline failed: {e}")
        import traceback
        traceback.print_exc() # Helps debug internal model failures quickly
        return

    # 4. Print results to observe the target metrics
    for i, payload in enumerate(batch_results):
        print("\n" + "=" * 50)
        print(f"ANALYSIS FOR NODE ID: {payload.get('id')}")
        print("=" * 50)

        # Check what the text preprocessing layer actually outputted
        print(f"\n[Engine Matrix Key Verification]:")
        # Checks the output matrix payload keys directly
        print(f"-> Generated Key 'cleaned_body': {'YES' if 'cleaned_body' in payload else 'NO'}")
        if "cleaned_body" in payload:
            print(f"-> Content Sample: {payload['cleaned_body'][:80]}...")

        print("\n[Pass 2a: Intent Classification Output]")
        print(json.dumps(to_serializable_dict(payload.get("classification")), indent=4))

        print("\n[Pass 2b: Action Extractor Placeholder]")
        print(json.dumps(to_serializable_dict(payload.get("actions")), indent=4))

        print("\n[Pass 2c: Structural Security Rules Metric]")
        print(json.dumps(to_serializable_dict(payload.get("security")), indent=4))


if __name__ == "__main__":
    # run_pipeline_integration_test()
    classifierPreProc = EmailPreprocessor()
    text = "Confirm your email address.\nFollow the link below to confirm this email address and finish signing up.\n\nConfirm email address: [https://qyjwniizxidrfrzjxguq.supabase.co/auth/v1/verify?token=f69c0d987a545032aacf9b5b425e5892d7488c14f680f4952c4cad4d&type=signup&redirect_to=http://localhost:3000/](https://qyjwniizxidrfrzjxguq.supabase.co/auth/v1/verify?token=f69c0d987a545032aacf9b5b425e5892d7488c14f680f4952c4cad4d&type=signup&redirect_to=http://localhost:3000/)\n\nYou are receiving this email because you signed up for an application powered by Supabase."
    cleaned_text = classifierPreProc.preprocess(text)
    print("cleaned text after pre proc: ",cleaned_text)
    test_single_text_payload()