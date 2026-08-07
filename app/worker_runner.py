import asyncio

from app.core.services.ml import MLCoreService, MLEngineService
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
        try:
            # 1. Run main ingestion (Fetches raw emails + streams live ML)
            await sync_worker.run_sync_cycle()
            # 2. Run recovery catch-up (Cleans up skipped onboarding or failed inference)
            await recovery_orchestrator.run_recovery_cycle()
            # 3. Run feature-level orchestration (Task Generation & Resolution)
            await feature_runner.run_cycle()

        except Exception as e:
            print(f"❌ [CRITICAL ERROR] Worker loop encountered a failure: {e}")
            print("Retrying automatically in the next cycle...")

        print("=== CYCLE COMPLETE. SLEEPING FOR 5 MIN ===")
        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())