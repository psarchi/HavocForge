.PHONY: help env up down logs restart ps shell test rebuild clean clean-all clean-data fmt lint lint-fix health db-shell redis-cli full-reset reset

COMPOSE       ?= docker compose
ENV_FILE      ?= .env
CONFIG        ?= config/default/server.yaml
ENV_SCRIPT    ?= scripts/gen_env.py
PY            ?= python
PROJECT_NAME  ?= $(if $(COMPOSE_PROJECT_NAME),$(COMPOSE_PROJECT_NAME),$(notdir $(CURDIR)))
NETWORK       ?= $(PROJECT_NAME)_havocforge
SERVICES      ?=
WITHOUT_ENV   ?= false
EXTRA_GOALS := $(filter-out logs fmt lint lint-fix restart,$(MAKECMDGOALS))

ifeq ($(strip $(EXTRA_GOALS)),)
EXTRA_GOALS :=
else
.PHONY: $(EXTRA_GOALS)
$(EXTRA_GOALS):
	@:
endif

help:
	@echo "make env                      - generate .env from $(CONFIG)"
	@echo "make up [SERVICES=...]        - start services (auto-generates .env)"
	@echo "make up WITHOUT_ENV=true      - start services using existing .env"
	@echo "make down                     - stop all services"
	@echo "make restart [SERVICE]        - restart a service (e.g. make restart api)"
	@echo "make logs [SERVICES]          - follow logs"
	@echo "make ps                       - list containers"
	@echo "make shell [SERVICE=api]      - shell into a service"
	@echo "make test [ARGS=...]          - run pytest in api container"
	@echo "make fmt | lint               - ruff format/check in api container"
	@echo "make clean                    - down + prune orphans/network"
	@echo "make clean-data               - clean + drop pg/redis volumes"
	@echo "make clean-all                - clean-data + docker system prune"
	@echo "make health                   - curl basic health checks"
	@echo "make full-reset               - clean -> env -> build -> up (no volume drop)"

env:
	@$(PY) $(ENV_SCRIPT) --config $(CONFIG) --output $(ENV_FILE)

ifeq ($(WITHOUT_ENV),true)
up:
	$(COMPOSE) $(SERVICES) up -d
else
up: env
	$(COMPOSE) $(SERVICES) up -d
endif

build:
	$(COMPOSE) $(SERVICES) build

down:
	$(COMPOSE) down $(SERVICES)

logs:
	$(COMPOSE) logs -f $(if $(SERVICES),$(SERVICES),$(EXTRA_GOALS))

restart:
	$(COMPOSE) restart $(if $(SERVICES),$(SERVICES),$(EXTRA_GOALS))

ps:
	$(COMPOSE) ps

shell:
	@service=$${SERVICE:-api}; \
	$(COMPOSE) exec $$service sh

test:
	$(COMPOSE) exec -T api pytest $(ARGS)

rebuild:
	@$(MAKE) clean-data
	@$(MAKE) build
	@$(MAKE) up

full-reset:
	@$(MAKE) clean
	@$(MAKE) env
	@$(MAKE) build
	@$(MAKE) up

reset:
	@$(MAKE) down
	@$(MAKE) env
	@$(MAKE) up

clean:
	$(COMPOSE) down -v --remove-orphans || true
	@docker ps -aq --filter "network=$(NETWORK)" | xargs -r docker rm -f
	@docker network rm $(NETWORK) 2>/dev/null || true

clean-all: clean-data
	docker system prune -f

clean-data: clean
	docker volume rm $(PROJECT_NAME)_pgdata $(PROJECT_NAME)_redisdata 2>/dev/null || true

fmt:
	$(COMPOSE) exec -T api ruff format .

lint:
	$(COMPOSE) exec -T api ruff check .

lint-fix:
	$(COMPOSE) exec -T api ruff check --fix .

health:
	@echo "=== API Health ==="
	@curl -s http://localhost:8000/v1/health || echo "API not responding"
	@echo "\n=== Prometheus Health ==="
	@curl -s http://localhost:9090/-/healthy || echo "Prometheus not responding"
	@echo "\n=== Grafana Health ==="
	@curl -s http://localhost:3000/api/health || echo "Grafana not responding"

db-shell:
	@USER=$$(grep -E '^PERSISTENCE_POSTGRES_USER=' $(ENV_FILE) | cut -d'=' -f2); \
	DB=$$(grep -E '^PERSISTENCE_POSTGRES_DB=' $(ENV_FILE) | cut -d'=' -f2); \
	USER=$${USER:-havocforge}; DB=$${DB:-havocforge}; \
	$(COMPOSE) exec postgres psql -U $$USER -d $$DB

redis-cli:
	$(COMPOSE) exec redis redis-cli
