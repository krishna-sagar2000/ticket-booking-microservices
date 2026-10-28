"""BR2 background job: every EXPIRY_INTERVAL_SECONDS, release holds whose time has passed.

The sweep is one UPDATE that only matches expired HELD rows (db.expire_holds), so it never
touches a SOLD seat and running it twice, or in several worker processes at once, is harmless.
"""
import asyncio
import logging

from . import config, rules

log = logging.getLogger("seat-service")


async def run_forever() -> None:
    while True:
        try:
            # the DB call blocks, so run it in a worker thread and keep the event loop free
            expired = (await asyncio.to_thread(rules.expire_holds))["expiredCount"]
            if expired:
                log.info("expiry job released %s expired hold(s)", expired)
        except Exception:  # a DB outage must not kill the job; try again next round
            log.exception("expiry job failed; retrying in %ss", config.EXPIRY_INTERVAL_SECONDS)
        await asyncio.sleep(config.EXPIRY_INTERVAL_SECONDS)
