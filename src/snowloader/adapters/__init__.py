"""Framework adapters for snowloader.

Thin wrappers that convert SnowDocument output from the core loaders into
document types expected by LangChain, LlamaIndex, or other LLM frameworks.
No business logic lives here. If you are looking for query building,
pagination, or field mapping, check the loaders package instead.

Import paths (adapters are not auto-imported to avoid pulling in optional
dependencies)::

    # LangChain
    from snowloader.adapters.langchain import ServiceNowIncidentLoader

    # LlamaIndex
    from snowloader.adapters.llamaindex import ServiceNowIncidentReader
"""
