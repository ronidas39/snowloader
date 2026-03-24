"""CMDB relationship graph example.

Demonstrates how to load CMDB configuration items with their
relationship graph. Each document includes directional arrows
showing how CIs depend on, contain, or host each other.

Usage:
    export SNOW_INSTANCE=https://mycompany.service-now.com
    export SNOW_USER=admin
    export SNOW_PASS=password
    python examples/05_cmdb_graph.py
"""

from __future__ import annotations

import logging
import os

from snowloader import CMDBLoader, SnowConnection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    conn = SnowConnection(
        instance_url=os.environ["SNOW_INSTANCE"],
        username=os.environ["SNOW_USER"],
        password=os.environ["SNOW_PASS"],
    )

    # Load servers with their relationships
    # include_relationships=True adds 2 API calls per CI
    loader = CMDBLoader(
        connection=conn,
        ci_class="cmdb_ci_server",
        include_relationships=True,
        query="operational_status=1",
    )

    for doc in loader.lazy_load():
        name = doc.metadata.get("name", "Unknown")
        logger.info("=== %s ===", name)
        logger.info("%s", doc.page_content)

        # Relationship data is also available as structured metadata
        outbound = doc.metadata.get("outbound_relations", [])
        inbound = doc.metadata.get("inbound_relations", [])
        logger.info(
            "  Relationships: %d outbound, %d inbound",
            len(outbound),
            len(inbound),
        )
        logger.info("")


if __name__ == "__main__":
    main()
