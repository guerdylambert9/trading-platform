# Shortcuts for macOS and Linux. On Windows, run the commands from the README instead.

BACKEND := backend
FRONTEND := frontend
BIN := .venv/bin

.PHONY: help install demo serve dashboard build test lint format check docker

help: ## List the shortcuts
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-10s %s\n", $$1, $$2}'

install: ## Set up the backend (with dev tools) and the dashboard
	cd $(BACKEND) && python3 -m venv .venv && $(BIN)/pip install -e ".[dev]"
	cd $(FRONTEND) && npm install

demo: ## Replay recent trading days with the fake broker
	cd $(BACKEND) && $(BIN)/trader demo

serve: ## Run the API (and the built dashboard) on http://127.0.0.1:8000
	cd $(BACKEND) && $(BIN)/trader serve

dashboard: ## Run the dashboard dev server on http://localhost:5173
	cd $(FRONTEND) && npm run dev

build: ## Type-check and build the dashboard into frontend/dist
	cd $(FRONTEND) && npm run build

test: ## Run the backend tests
	cd $(BACKEND) && $(BIN)/pytest

lint: ## Check style without changing files
	cd $(BACKEND) && $(BIN)/ruff check . && $(BIN)/ruff format --check .

format: ## Fix style
	cd $(BACKEND) && $(BIN)/ruff check --fix . && $(BIN)/ruff format .

check: lint test build ## Everything CI runs

docker: ## Start Postgres and the app with Docker Compose
	docker compose up -d --build
