.PHONY: dev build deploy logs test clean

# Development
dev:
	python -m src.main

install:
	pip install -e ".[dev]"

# Docker
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f bot

# Deploy to server
deploy:
	rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.env' \
		./ root@65.109.142.30:/opt/telegram-ai-bot/
	ssh root@65.109.142.30 "cd /opt/telegram-ai-bot && docker compose up -d --build"

# Database migrations
migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migrate-new:
	@read -p "Migration message: " msg; alembic revision -m "$$msg"

# Testing
test:
	pytest -v

lint:
	ruff check src/

format:
	ruff format src/

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
