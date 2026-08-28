Adapter files must be THIN wrappers only.
Zero business logic — all logic lives in core loaders.
Each adapter class should be under 15 lines of unique code.
Use try/except ImportError with helpful install message.
LangChain: inherit from langchain_core.document_loaders.BaseLoader
LlamaIndex: inherit from llama_index.core.readers.base.BaseReader
