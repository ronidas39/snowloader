"""Framework adapters for snowloader.

Thin wrappers that convert SnowDocument output from the core loaders into
document types expected by LangChain, LlamaIndex, or other LLM frameworks.
No business logic lives here. If you are looking for query building,
pagination, or field mapping, check the loaders package instead.
"""
