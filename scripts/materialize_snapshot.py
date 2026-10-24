import asyncio
from datetime import datetime, timezone
from trend_system.database.session import get_async_sessionmaker
from trend_system.scheduler.snapshot import materialize_snapshot

async def main():
    async with get_async_sessionmaker()() as session:
        snap = await materialize_snapshot(session, datetime.now(timezone.utc))
        print(f"snapshot with {len(snap)} trends")

if __name__ == "__main__":
    asyncio.run(main())
