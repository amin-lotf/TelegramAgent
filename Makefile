HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)

COMPOSE = HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) docker compose

.PHONY: up up-build down restart ps logs \
        logs-storage logs-app logs-celery logs-n8n logs-vllm logs-whisperx \
        shell-app shell-celery migrate heads

up:
	$(COMPOSE) up -d

up-build:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

down-v:
	$(COMPOSE) down -v

restart:
	$(COMPOSE) down
	$(COMPOSE) up -d

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

logs-storage:
	$(COMPOSE) logs -f --tail=100 telegram-ingress-migrate  telegram-auth-migrate n8n_postgres telegram_auth_postgres telegram_ingress_postgres  redis

logs-app:
	$(COMPOSE) logs -f --tail=100  telegram-auth telegram-ingress content-processing

logs-celery:
	$(COMPOSE) logs -f --tail=100   content-processing-worker:

logs-n8n:
	$(COMPOSE) logs -f --tail=100 n8n

logs-vllm:
	$(COMPOSE) logs -f --tail=100 vllm-whisper

logs-whisperx:
	$(COMPOSE) logs -f --tail=100 whisperx



shell-celery:
	$(COMPOSE) exec video-processing-worker bash

migrate-telegram-auth:
	$(COMPOSE) run --rm telegram-auth-migrate alembic -n telegram_auth upgrade head

migrate-telegram-ingress:
	$(COMPOSE) run --rm telegram-ingress-migrate alembic -n telegram_ingress upgrade head

migrate-content_processing:
	$(COMPOSE) run --rm content-processing-migrate alembic -n content_processing upgrade head

heads-telegram-ingress:
	$(COMPOSE) run --rm telegram-ingress-migrate alembic -n telegram_ingress heads



revision-telegram-auth:
	$(COMPOSE) run --rm telegram-auth-migrate alembic -n telegram_auth  revision --autogenerate -m "$(msg)"

revision-telegram-ingress:
	$(COMPOSE) run --rm telegram-ingress-migrate alembic -n telegram_ingress  revision --autogenerate -m "$(msg)"

revision-content-processing:
	$(COMPOSE) run --rm content-processing-migrate alembic -n content_processing  revision --autogenerate -m "$(msg)"
