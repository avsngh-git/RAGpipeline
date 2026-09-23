# Scientific Research Platform

An installable Python project for a scientific literature research platform.

## Development environment

This project uses Conda as its development dependency manager.

Create the environment from the human-maintained specification:

```bash
conda env create --file environment.yaml
conda activate sci_research_agent
python -m pip install --no-build-isolation --no-deps -e .
```

The editable installation makes the local `src/` package importable while
keeping source changes immediately available to the environment.

Run the project checks from the repository root:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

## Locked Linux environment

`environment-linux-64.lock` is an exact Conda package lock for Linux x86-64.
Use it when reproducing the currently tested Linux environment:

```bash
conda create \
  --name sci_research_agent_linux \
  --file environment-linux-64.lock

conda run -n sci_research_agent_linux \
  python -m pip install --no-build-isolation --no-deps -e .
```

The local package is installed separately because the lock file contains the
Conda environment packages, not the repository's editable source tree.

## Application configuration

`research_platform.config.Settings` reads configuration from process
environment variables and validates it when a settings object is created.
Supported variables are:

- `RESEARCH_PLATFORM_ENVIRONMENT`: `development`, `test`, or `production`.
- `RESEARCH_PLATFORM_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or
  `CRITICAL`.
- `RESEARCH_PLATFORM_DATABASE_URL`: a PostgreSQL connection URL.
- `RESEARCH_PLATFORM_QDRANT_URL`: an HTTP or HTTPS Qdrant URL.
- `RESEARCH_PLATFORM_DEPENDENCY_TIMEOUT_SECONDS`: positive timeout for readiness
  checks.

`.env.example` documents safe local-development values. It is not loaded
automatically by the standard library configuration code; copy it to `.env`
and export those values in the shell, or provide the variables through Docker
Compose. `.env` is ignored by Git and must contain any real credentials.

Invalid values raise `ValueError` during `Settings()` construction so an
application fails at startup with a clear configuration error.

## Run the API

Start the development server with Uvicorn:

```bash
python -m uvicorn research_platform.api:create_app \
  --factory \
  --reload
```

Check process liveness:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Logging and errors

The API assigns every HTTP request an `X-Request-ID`. A caller-provided ID is
preserved when it is non-empty and reasonably bounded; otherwise the API
generates a UUID. The ID is returned in the response and is available to
request handlers and structured logs.

Application logs are emitted as JSON with timestamps, levels, logger names,
request IDs, and safe HTTP metadata. Expected failures can raise `AppError`
and return a structured response containing an error code, message, and
request ID. Unexpected failures return a generic `internal_error` response;
diagnostic exception details stay in server logs rather than being exposed to
clients.

## Local services and migrations

Start PostgreSQL, Qdrant, and the API together:

```bash
docker compose up --build
```

The services use named volumes so ordinary restarts preserve local data.
Verify liveness and dependency readiness separately:

```bash
curl http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Apply the versioned PostgreSQL schema from the host environment:

```bash
conda activate sci_research_agent
python scripts/migrate.py
```

The migration runner records applied versions in `schema_migrations` and is
safe to run again. The Qdrant index remains a derived store and is not part
of the relational migration.

## Environment files

- `environment.yaml` is the human-maintained Conda environment definition.
- `environment-linux-64.lock` records exact package builds for Linux x86-64.
- `pyproject.toml` defines the Python package and configures build, linting,
  type checking, and testing tools.

The YAML specification is the normal starting point for a new environment.
The lock file is platform-specific and should be regenerated after deliberate
environment changes.
