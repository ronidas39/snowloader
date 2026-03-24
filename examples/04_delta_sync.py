"""Delta sync example — only fetch updated records.

Demonstrates how to use load_since() to incrementally sync ServiceNow
data. On the first run, all records are loaded. On subsequent runs,
only records updated after the last sync timestamp are fetched.

Usage:
    export SNOW_INSTANCE=https://mycompany.service-now.com
    export SNOW_USER=admin
    export SNOW_PASS=password
    python examples/04_delta_sync.py
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from snowloader import IncidentLoader, SnowConnection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYNC_STATE_FILE = Path("sync_state.json")


def load_sync_state() -> datetime | None:
    """Load the last sync timestamp from disk."""
    if SYNC_STATE_FILE.exists():
        data = json.loads(SYNC_STATE_FILE.read_text())
        return datetime.fromisoformat(data["last_sync"])
    return None


def save_sync_state(timestamp: datetime) -> None:
    """Persist the sync timestamp to disk."""
    SYNC_STATE_FILE.write_text(json.dumps({"last_sync": timestamp.isoformat()}))


def main() -> None:
    conn = SnowConnection(
        instance_url=os.environ["SNOW_INSTANCE"],
        username=os.environ["SNOW_USER"],
        password=os.environ["SNOW_PASS"],
    )

    loader = IncidentLoader(connection=conn, query="active=true")
    last_sync = load_sync_state()

    if last_sync:
        logger.info("Delta sync: fetching records updated since %s", last_sync)
        docs = loader.load_since(last_sync)
    else:
        logger.info("Initial sync: loading all records")
        docs = loader.load()

    logger.info("Loaded %d documents", len(docs))
    for doc in docs:
        logger.info("  %s: %s", doc.metadata.get("number"), doc.page_content[:80])

    # Save the current time as the new sync point
    save_sync_state(datetime.now(timezone.utc))
    logger.info("Sync state saved")


if __name__ == "__main__":
    main()
