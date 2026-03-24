"""LlamaIndex RAG pipeline with ServiceNow Knowledge Base articles.

Shows how to use the LlamaIndex adapter to load KB articles into a
VectorStoreIndex and query them.

Requires:
    pip install snowloader[llamaindex] llama-index-llms-openai llama-index-embeddings-openai

Usage:
    export SNOW_INSTANCE=https://mycompany.service-now.com
    export SNOW_USER=admin
    export SNOW_PASS=password
    export OPENAI_API_KEY=sk-...
    python examples/03_llamaindex_rag.py
"""

from __future__ import annotations

import os

from llama_index.core import VectorStoreIndex

from snowloader import SnowConnection
from snowloader.adapters.llamaindex import ServiceNowKBReader


def main() -> None:
    conn = SnowConnection(
        instance_url=os.environ["SNOW_INSTANCE"],
        username=os.environ["SNOW_USER"],
        password=os.environ["SNOW_PASS"],
    )

    # Load published KB articles through the LlamaIndex adapter
    reader = ServiceNowKBReader(
        connection=conn,
        query="workflow_state=published",
    )
    docs = reader.load_data()

    # Build an index and query it
    index = VectorStoreIndex.from_documents(docs)
    query_engine = index.as_query_engine()

    response = query_engine.query("How do I reset my VPN password?")
    print(response)


if __name__ == "__main__":
    main()
