import asyncio

from app.core.services.ml import MLCoreService
from app.core.workers.sync_worker import EmailSyncWorker
from app.core.workers.ml_recovery_orchestrator import MLRecoveryOrchestrator
import app.core.ml_models.fact_extractor.spacy_engine
from app.feature_runner import FeatureWorkerRunner

# The main periodic worker orchestrator

async def main():
    ml_engine = MLCoreService()

    sync_worker = EmailSyncWorker(ml_engine=ml_engine)
    recovery_orchestrator = MLRecoveryOrchestrator(ml_engine=ml_engine)
    feature_runner = FeatureWorkerRunner()

    print("🚀 [SERVER] Worker Runner Daemon Active.")

    while True:
        print("\n=== STARTING INTEGRATED CYCLE ===")
        remaining_onboarding = 0
        try:
            # 1. Run high-priority onboarding backfills (Round-robin capped, non-blocking)
            remaining_onboarding = await sync_worker.run_onboarding_cycle(max_batches_per_account=2)

            # 2. Run routine active email sync (Fetches raw emails + streams live ML for ACTIVE accounts)
            await sync_worker.run_sync_cycle()

            # 3. Run recovery catch-up (Cleans up skipped onboarding or failed inference)
            await recovery_orchestrator.run_recovery_cycle()

            # 4. Run feature-level orchestration (Task Generation & Resolution)
            await feature_runner.run_cycle()

        except Exception as e:
            print(f"❌ [CRITICAL ERROR] Worker loop encountered a failure: {e}")
            print("Retrying automatically in the next cycle...")

        if remaining_onboarding > 0:
            print(f"=== CYCLE COMPLETE. {remaining_onboarding} ONBOARDING ACCOUNT(S) PENDING. SLEEPING FOR 10s ===")
            await asyncio.sleep(10)
        else:
            print("=== CYCLE COMPLETE. ALL ACCOUNTS ACTIVE. SLEEPING FOR 5 MIN ===")
            await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())