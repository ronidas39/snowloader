"""LangChain RAG pipeline with ServiceNow incidents.

Shows how to use the LangChain adapter to load incidents into a FAISS
vector store and query them with a retrieval chain.

Requires:
    pip install snowloader[langchain] langchain-openai faiss-cpu

Usage:
    export SNOW_INSTANCE=https://mycompany.service-now.com
    export SNOW_USER=admin
    export SNOW_PASS=password
    export OPENAI_API_KEY=sk-...
    python examples/02_langchain_rag.py
"""

from __future__ import annotations

import os

from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from snowloader import SnowConnection
from snowloader.adapters.langchain import ServiceNowIncidentLoader


def main() -> None:
    conn = SnowConnection(
        instance_url=os.environ["SNOW_INSTANCE"],
        username=os.environ["SNOW_USER"],
        password=os.environ["SNOW_PASS"],
    )

    # Load incidents through the LangChain adapter
    loader = ServiceNowIncidentLoader(
        connection=conn,
        query="active=true^priority<=2",
    )
    docs = loader.load()

    # Build a vector store
    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(docs, embeddings)

    # Query
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    results = retriever.invoke("network outage incidents")

    for doc in results:
        print(f"[{doc.metadata.get('number')}] {doc.page_content[:200]}")
        print()


if __name__ == "__main__":
    main()
