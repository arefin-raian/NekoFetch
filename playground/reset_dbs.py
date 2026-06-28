import asyncio
from nekofetch.core.config import get_env

async def main():
    env = get_env()

    # ── Mongo: drop runtime config overrides so config.yaml (codebase) wins ──
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo = AsyncIOMotorClient(env.mongo_uri, serverSelectionTimeoutMS=15000)[env.mongo_db]
    before = await mongo.settings.find_one({"key": "runtime_overrides"})
    fields = sum(len(v) for v in (before or {}).get("value", {}).values()
                 if isinstance(v, dict)) if before else 0
    await mongo.settings.update_one({"key": "runtime_overrides"},
                                    {"$set": {"value": {}}}, upsert=True)
    print(f"mongo: cleared {fields} runtime override field(s) -> config.yaml authoritative")

    # ── Redis: clear stale log-channel + FSM state so it self-heals on restart ──
    from redis.asyncio import Redis
    r = Redis.from_url(env.redis_url, decode_responses=True)
    total = 0
    for pattern in ("nf:logcc:*", "nf:logpin:*", "nf:fsm:*"):
        keys = [k async for k in r.scan_iter(match=pattern, count=200)]
        if keys:
            await r.delete(*keys)
        print(f"redis: deleted {len(keys)} key(s) matching {pattern}")
        total += len(keys)
    await r.aclose()
    print(f"DONE — mongo overrides cleared, {total} redis keys cleared")

asyncio.run(main())
