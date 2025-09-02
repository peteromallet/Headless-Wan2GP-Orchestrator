#!/usr/bin/env python3
"""Dev helper to run both GPU and API orchestrators in one process.

Not recommended for production. Intended for local testing only.
"""

import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))


async def run_gpu_single_cycle():
    from gpu_orchestrator.main import main as gpu_main
    # Reuse the existing CLI which supports single/continuous; here we just call main
    gpu_main()


async def run_api_orchestrator():
    from api_orchestrator.main import main_async as api_main_async
    await api_main_async()


async def main():
    # Run GPU orchestrator in a background task (single or continuous based on env)
    gpu_task = asyncio.create_task(run_gpu_single_cycle())
    # Run API orchestrator continuously
    await run_api_orchestrator()
    await gpu_task


if __name__ == "__main__":
    asyncio.run(main())


