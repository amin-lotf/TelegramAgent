HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)

COMPOSE = HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) docker compose
DUBBING_WORKLOAD_LOG_ROOT ?= media/.gpu-control
MADLAD_ENV_FILE ?= docker/madlad/.env.madlad.docker

.PHONY: up up-build setup-dubbing up-dubbing build-dubbing init-dubbing-models \
        prepare-madlad-storage sync-madlad-weights build-madlad up-madlad up-with-madlad rebuild-madlad \
        stop-madlad restart-madlad reload-madlad-adapter \
        down down-v restart ps logs \
        logs-storage logs-app logs-celery logs-n8n logs-gpu-execution \
        logs-dubbing logs-cosyvoice logs-sam logs-madlad \
        logs-admin-dashboard \
        logs-telegram-bot-api \
        shell-celery \
        migrate-telegram-auth migrate-telegram-ingress migrate-content_processing migrate-agent-runtime migrate-gpu-execution \
        heads-telegram-ingress \
        revision-telegram-auth revision-telegram-ingress revision-content-processing revision-agent-runtime revision-gpu-execution

up:
	$(COMPOSE) up -d

up-build:
	$(COMPOSE) up -d --build $(SERVICE)

# Run once initially, and again only after changing the dubbing model runtimes,
# model selection, or dubbing database schema.
setup-dubbing:
	$(MAKE) build-dubbing
	$(MAKE) init-dubbing-models
	$(MAKE) migrate-content_processing

# Convenience target for setup/rebuild followed by stack startup.
up-dubbing:
	$(MAKE) setup-dubbing
	$(COMPOSE) up -d

build-dubbing:
	$(COMPOSE) --profile dubbing-init build gpu-dubbing-models-init gpu-execution-worker content-processing content-processing-worker

init-dubbing-models:
	$(COMPOSE) --profile dubbing-init run --rm gpu-dubbing-models-init

prepare-madlad-storage:
	mkdir -p pretrained_models/madlad/adapter pretrained_models/madlad-hf-cache

sync-madlad-weights: prepare-madlad-storage
	python3 scripts/sync_madlad_adapter.py --env-file $(MADLAD_ENV_FILE)

build-madlad:
	$(COMPOSE) build madlad

up-madlad: prepare-madlad-storage
	$(COMPOSE) --profile madlad up -d madlad

up-with-madlad: prepare-madlad-storage
	$(COMPOSE) --profile madlad up -d

rebuild-madlad:
	$(MAKE) sync-madlad-weights
	$(COMPOSE) --profile madlad up -d --build --force-recreate madlad

stop-madlad:
	$(COMPOSE) --profile madlad stop madlad

restart-madlad:
	$(COMPOSE) --profile madlad restart madlad

reload-madlad-adapter:
	$(COMPOSE) --profile madlad exec -T madlad python -c "import urllib.request; print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/v1/reload-adapter', method='POST'), timeout=30).read().decode())"

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
	$(COMPOSE) logs -f --tail=100 telegram-ingress-migrate telegram-auth-migrate gpu-execution-migrate n8n_postgres telegram_auth_postgres telegram_ingress_postgres agent_runtime_postgres gpu_execution_postgres redis

logs-app:
	$(COMPOSE) logs -f --tail=100 telegram-auth telegram-ingress content-processing agent-runtime llm_gateway gpu-execution

logs-admin-dashboard:
	$(COMPOSE) logs -f --tail=100 admin-dashboard

logs-celery:
	$(COMPOSE) logs -f --tail=100 content-processing-worker content-processing-beat telegram-ingress-worker telegram-ingress-beat agent-runtime-worker agent-runtime-beat gpu-execution-worker gpu-execution-control-worker gpu-execution-beat

logs-n8n:
	$(COMPOSE) logs -f --tail=100 n8n

logs-gpu-execution:
	$(COMPOSE) logs -f --tail=100 gpu-execution gpu-execution-worker gpu-execution-control-worker gpu-execution-beat

# Live orchestration and singleton GPU-worker logs for the complete dub flow.
logs-dubbing:
	$(COMPOSE) logs -f --tail=100 content-processing-worker gpu-execution-worker gpu-execution-control-worker

# Model subprocesses write attempt logs under media/.gpu-control/<gpu-job>/.
logs-cosyvoice:
	@descriptors=$$(grep -rl --include=descriptor.json '"workload_type": "cosyvoice.dubbing_batch.v1"' "$(DUBBING_WORKLOAD_LOG_ROOT)" 2>/dev/null || true); \
	logs=""; \
	for descriptor in $$descriptors; do \
		log="$${descriptor%descriptor.json}workload.log"; \
		if [ -f "$$log" ]; then logs="$$logs $$log"; fi; \
	done; \
	if [ -z "$$logs" ]; then \
		echo "No CosyVoice workload logs found under $(DUBBING_WORKLOAD_LOG_ROOT)"; \
		exit 0; \
	fi; \
	tail -F $$logs

logs-sam:
	@descriptors=$$(grep -rl --include=descriptor.json '"workload_type": "sam_audio.residual.v1"' "$(DUBBING_WORKLOAD_LOG_ROOT)" 2>/dev/null || true); \
	logs=""; \
	for descriptor in $$descriptors; do \
		log="$${descriptor%descriptor.json}workload.log"; \
		if [ -f "$$log" ]; then logs="$$logs $$log"; fi; \
	done; \
	if [ -z "$$logs" ]; then \
		echo "No SAM Audio workload logs found under $(DUBBING_WORKLOAD_LOG_ROOT)"; \
		exit 0; \
	fi; \
	tail -F $$logs

logs-madlad:
	$(COMPOSE) --profile madlad logs -f --tail=100 madlad

logs-telegram-bot-api:
	$(COMPOSE) logs -f --tail=100 telegram-bot-api



shell-celery:
	$(COMPOSE) exec video-processing-worker bash

migrate-telegram-auth:
	$(COMPOSE) run --rm telegram-auth-migrate alembic -n telegram_auth upgrade head

migrate-telegram-ingress:
	$(COMPOSE) run --rm telegram-ingress-migrate alembic -n telegram_ingress upgrade head

migrate-content_processing:
	$(COMPOSE) run --rm content-processing-migrate alembic -n content_processing upgrade head

migrate-agent-runtime:
	$(COMPOSE) run --rm agent-runtime-migrate alembic -n agent_runtime upgrade head

migrate-gpu-execution:
	$(COMPOSE) run --rm gpu-execution-migrate alembic -n gpu_execution upgrade head

heads-telegram-ingress:
	$(COMPOSE) run --rm telegram-ingress-migrate alembic -n telegram_ingress heads



revision-telegram-auth:
	$(COMPOSE) run --rm telegram-auth-migrate alembic -n telegram_auth  revision --autogenerate -m "$(msg)"

revision-telegram-ingress:
	$(COMPOSE) run --rm telegram-ingress-migrate alembic -n telegram_ingress  revision --autogenerate -m "$(msg)"

revision-content-processing:
	$(COMPOSE) run --rm content-processing-migrate alembic -n content_processing  revision --autogenerate -m "$(msg)"

revision-agent-runtime:
	$(COMPOSE) run --rm agent-runtime-migrate alembic -n agent_runtime revision --autogenerate -m "$(msg)"

revision-gpu-execution:
	$(COMPOSE) run --rm gpu-execution-migrate alembic -n gpu_execution revision --autogenerate -m "$(msg)"
