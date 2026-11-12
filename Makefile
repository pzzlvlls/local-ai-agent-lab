DS ?= all
LANGGRAPH ?= .venv/Scripts/langgraph.exe
PYTHON ?= .venv/Scripts/python.exe
HOST ?= 0.0.0.0
PORT ?= 80

.PHONY: docker-recreate build dev debug course course-push test-benchmark test-integrations

docker-recreate build dev debug course course-push test-benchmark test-integrations: export PYTHONUTF8 := 1
docker-recreate build dev debug course course-push test-benchmark test-integrations: export PYTHONIOENCODING := utf-8
docker-recreate build dev debug course course-push test-benchmark test-integrations: export PYTHONDONTWRITEBYTECODE := 1

docker-recreate:
	docker compose up -d --force-recreate

build:
	$(LANGGRAPH) build -t langgraph-python-agent:$(TAG)

dev:
	$(LANGGRAPH) dev --host $(HOST) --port $(PORT) --allow-blocking --no-reload

debug:
	$(LANGGRAPH) dev --host $(HOST) --port $(PORT) --debug-port 5678 --allow-blocking --no-reload

course:
	$(PYTHON) scripts/course.py

test-benchmark:
	BENCHMARK_DATASET="$(DS)" $(PYTHON) -m pytest -q -s --tb=no tests/benchmarks/test_benchmark.py

test-units:
	uv run pytest -q tests/units

test-integrations: export MINIO_INTEGRATION := 1
test-integrations: export DEPLOY_INTEGRATION := 1
test-integrations: export DEPLOY_SANDBOX_IMAGE := opensandbox-python-node:1.0
test-integrations:
	uv run pytest -q tests/integrations

course-push:
	@[ -n "$(SHA)" ] || (echo "请提供提交 hash: make course-push SHA=<hash>" && exit 1)
	$(PYTHON) scripts/course-push.py $(SHA)
