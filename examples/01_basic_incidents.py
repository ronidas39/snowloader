"""Basic incident loading example.

Demonstrates the simplest snowloader workflow: connect to ServiceNow,
load incidents, and iterate over the resulting documents.

Usage:
    export SNOW_INSTANCE=https://mycompany.service-now.com
    export SNOW_USER=admin
    export SNOW_PASS=password
    python examples/01_basic_incidents.py
"""

from __future__ import annotations

import logging
import os

from snowloader import IncidentLoader, SnowConnection

logging.basicConfig(level=logging.INFO)


def main() -> None:
    conn = SnowConnection(
        instance_url=os.environ["SNOW_INSTANCE"],
        username=os.environ["SNOW_USER"],
        password=os.environ["SNOW_PASS"],
    )

    # Load active, high-priority incidents
    loader = IncidentLoader(
        connection=conn,
        query="active=true^priority<=2",
    )

    # lazy_load() streams one document at a time — memory efficient
    for doc in loader.lazy_load():
        logging.info(
            "%-12s %s",
            doc.metadata.get("number", ""),
            doc.page_content[:120].replace("\n", " "),
        )


if __name__ == "__main__":
    main()
