# NetForge — developer convenience targets (compose files live in infra/).
# `make help` lists everything.
.PHONY: help install up prod down reset rebuild build logs ps backend frontend migrate clean

# Compose invocations (run from repo root; -f points into infra/).
DC      := docker compose
DEV     := -f infra/docker-compose.yml -f infra/docker-compose.lan.yml
PROD    := -f infra/docker-compose.prod.yml --env-file infra/.env.prod
HTTP_PORT ?= 8090
export HTTP_PORT

help:          ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:       ## One-shot installer (generates .env, builds, starts, waits for health)
	@bash install.sh

up:            ## Build & start the dev stack + LAN gateway (nginx on :$(HTTP_PORT))
	$(DC) $(DEV) up -d --build

prod:          ## Start the production stack (immutable images, nginx, scale)
	$(DC) $(PROD) up -d --build

down:          ## Stop the stack
	$(DC) $(DEV) down

reset:         ## Stop and DELETE all data (volumes)
	$(DC) $(DEV) down -v

rebuild:       ## Rebuild images from scratch (no cache)
	$(DC) $(DEV) build --no-cache

build:         ## Build images
	$(DC) $(DEV) build

logs:          ## Tail logs
	$(DC) $(DEV) logs -f

ps:            ## Show running services
	$(DC) $(DEV) ps

backend:       ## Run backend locally (needs Postgres + Redis + venv)
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:      ## Run frontend dev server
	cd frontend && npm run dev

migrate:       ## Apply SQL migrations into the running Postgres container (psql)
	@for f in infra/db/migrations/*.up.sql; do \
	  echo "==> applying $$f"; \
	  $(DC) $(DEV) exec -T postgres psql -U netforge -d netforge -v ON_ERROR_STOP=1 < "$$f"; \
	done

clean:         ## Remove dangling images/build cache
	docker image prune -f
