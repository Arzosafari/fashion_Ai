
from sqlalchemy import text
import asyncio, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from trend_system.database.session import get_async_sessionmaker

async def clean():
    async with get_async_sessionmaker()() as session:
        await session.execute(text("DELETE FROM trend_signals WHERE source_id IN ('banimode_mag','modeworld','digikala_mag') OR concept LIKE '__synth%' OR concept LIKE '__evidence%'"))
        await session.execute(text("DELETE FROM trends WHERE canonical_name LIKE '__synth%' OR canonical_name LIKE '__evidence%'"))
        await session.execute(text("DELETE FROM trend_history WHERE trend_id LIKE '__synth%' OR trend_id LIKE '__evidence%'"))
        await session.execute(text("DELETE FROM trend_evidence WHERE trend_id LIKE '__synth%' OR trend_id LIKE '__evidence%'"))
        await session.commit()
        print("cleaned old iranian + synthetic signals")

asyncio.run(clean())