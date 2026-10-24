import asyncio, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from datetime import datetime, timezone
from trend_system.database.session import get_async_sessionmaker
from trend_system.scheduler.snapshot import materialize_snapshot

async def main():
    async with get_async_sessionmaker()() as s:
        p = await materialize_snapshot(s, datetime.now(timezone.utc), exclude_synthetic=True)
        print(f"snapshot: {len(p)} trends -> {[x['canonical_name'] for x in p[:5]]}")

asyncio.run(main())