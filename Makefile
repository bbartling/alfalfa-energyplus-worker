.PHONY: test lint alfalfa-config alfalfa quickstart energyplus-smoke

test:
	pytest

lint:
	ruff check .

# Render the Alfalfa Compose file and fail if the S3 URL is not reachable in-network.
alfalfa-config:
	bash scripts/launch.sh config

alfalfa:
	bash scripts/launch.sh up

quickstart:
	docker compose --profile demo up --build -d
	@echo "Dashboard: http://127.0.0.1:$${TWIN_HTTP_PORT:-18080}"

energyplus-smoke:
	pytest -o addopts='-q -m energyplus'
