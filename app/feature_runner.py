from app.core.workers.thread_orchestrator import ThreadOrchestrator

class FeatureWorkerRunner:
    def __init__(self):
        self.orchestrator = ThreadOrchestrator()

    async def run_cycle(self):
        """
        Orchestrates feature-level workers.
        Runs the unified thread processing orchestrator.
        """
        print("\n--- [FeatureRunner] Starting Feature Cycle ---")
        try:
            await self.orchestrator.run_cycle()
        except Exception as e:
            print(f"❌ [FeatureRunner ERROR] Cycle failed: {e}")
        print("--- [FeatureRunner] Feature Cycle Complete ---\n")
