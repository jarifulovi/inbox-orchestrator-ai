from app.core.workers.task_generation_worker import TaskGenerationWorker
from app.core.workers.task_resolution_worker import TaskResolutionWorker

class FeatureWorkerRunner:
    def __init__(self):
        self.generation_worker = TaskGenerationWorker()
        self.resolution_worker = TaskResolutionWorker()

    async def run_cycle(self):
        """
        Orchestrates feature-level workers.
        Runs task generation followed by task resolution.
        """
        print("\n--- [FeatureRunner] Starting Feature Cycle ---")
        try:
            await self.generation_worker.run_generation_cycle()
            await self.resolution_worker.run_resolution_cycle()
        except Exception as e:
            print(f"❌ [FeatureRunner ERROR] Cycle failed: {e}")
        print("--- [FeatureRunner] Feature Cycle Complete ---\n")
