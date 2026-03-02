"""
Bolt feed — DISABLED (stub).
The auto-discovery bot does not use Bolt for now.
"""
import asyncio


async def run_bolt_client():
    """No-op stub. Bolt is disabled."""
    print("⚡ [BOLT] Disabled — running without sportsbook odds feed.")
    while True:
        await asyncio.sleep(3600)
