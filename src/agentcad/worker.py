"""A cancelled waiter cannot release a running CAD worker's serialization slot."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial


class CADWorker:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agentcad")

    async def run(self, fn, *args, **kwargs):
        future = asyncio.get_running_loop().run_in_executor(self.executor, partial(fn, *args, **kwargs))
        # Cancellation stops waiting, not the thread. The executor retains its slot until it really ends.
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        return await asyncio.shield(future)

    def close(self):
        self.executor.shutdown(wait=True)
