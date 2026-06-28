import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nekofetch.core.config import get_env

async def main():
    env = get_env()  # reads .env
    engine = create_async_engine(env.postgres_dsn)
    # FK-safe delete order for workflow/test data; keep users + bots.
    tables = ["files", "download_queue", "analytics_events", "channel_posts", "requests"]
    async with engine.begin() as conn:
        print("=== before ===")
        for tbl in tables:
            try:
                n = (await conn.execute(text(f"SELECT count(*) FROM {tbl}"))).scalar()
                print(f"  {tbl}: {n}")
            except Exception as e:
                print(f"  {tbl}: (skip) {e}")
        for tbl in tables:
            try:
                await conn.execute(text(f"DELETE FROM {tbl}"))
            except Exception as e:
                print(f"  delete {tbl} failed: {e}")
        print("=== after ===")
        for tbl in tables:
            try:
                n = (await conn.execute(text(f"SELECT count(*) FROM {tbl}"))).scalar()
                print(f"  {tbl}: {n}")
            except Exception:
                pass
    await engine.dispose()
    print("DONE")

asyncio.run(main())
