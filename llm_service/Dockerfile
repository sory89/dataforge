# syntax=docker/dockerfile:1
# IMPORTANT : le contexte de build est la RACINE du depot (pas llm_service/),
# car l'image embarque la base DuckDB construite par dbt.
#   docker build -f llm_service/Dockerfile -t llm-service:local .

# --- Etape 1 : dependances du service ---
FROM python:3.12-slim AS deps
WORKDIR /app
COPY llm_service/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Etape 2 : construction de la base DuckDB avec dbt ---
FROM python:3.12-slim AS dbtbuild
RUN pip install --no-cache-dir dbt-core==1.8.5 dbt-duckdb==1.8.3
COPY dbt/ /build/dbt/
WORKDIR /build/dbt
RUN dbt build --target dev --profiles-dir . && test -f dataforge.duckdb

# --- Etape 3 : runtime minimal ---
FROM python:3.12-slim
RUN useradd --create-home appuser && mkdir -p /data
WORKDIR /app
COPY --from=deps /install /usr/local
COPY llm_service/app/ app/
COPY --from=dbtbuild /build/dbt/dataforge.duckdb /data/dataforge.duckdb
RUN chown -R appuser:appuser /data /app
USER appuser
ENV DUCKDB_PATH=/data/dataforge.duckdb
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
