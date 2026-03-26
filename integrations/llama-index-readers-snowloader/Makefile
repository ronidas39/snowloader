format:
	ruff format llama_index/ tests/
	ruff check --fix llama_index/ tests/

lint:
	ruff check llama_index/ tests/
	ruff format --check llama_index/ tests/

test:
	pytest tests/ -x --tb=short -q
