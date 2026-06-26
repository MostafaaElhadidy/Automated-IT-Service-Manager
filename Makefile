.PHONY: setup migrate seed ingest backend chat dashboard mcp test eval demo-setup demo

VENV ?= .venv
PYTHON := $(VENV)/Scripts/python  # Windows
# For Mac/Linux use: $(VENV)/bin/python

setup:
	python -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

db-up:
	docker compose up -d db

migrate:
	alembic upgrade head

seed:
	$(PYTHON) -m synapse.db.seed

ingest:
	$(PYTHON) -m synapse.rag.ingest

backend:
	$(PYTHON) -m uvicorn synapse.api.main:app --reload --port 8000

chat:
	chainlit run ui/chat_app.py --port 8001

dashboard:
	streamlit run ui/dashboard.py --server.port 8502

mcp:
	$(PYTHON) -m synapse.mcp_servers.runbook_server

test:
	$(PYTHON) -m pytest -v

eval:
	$(PYTHON) -m synapse.eval.harness

demo-setup: setup db-up migrate seed ingest
	@echo ""
	@echo "Setup complete! Now run:"
	@echo "  make backend   (terminal 1)"
	@echo "  make chat      (terminal 2)"
	@echo "  make dashboard (terminal 3)"
