FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM apache/airflow:3.3.2-python3.11@sha256:a6685a7a708ed6fa910c2c05458d7f2b0db9cca5c3bf58a72ded389767ad3e65

USER root

COPY --from=uv /uv /usr/local/bin/uv
COPY dbt/requirements.txt /opt/dbt-requirements.txt

RUN uv venv /opt/dbt-venv --python /usr/local/bin/python \
    && uv pip install --python /opt/dbt-venv/bin/python --require-hashes --no-cache \
       -r /opt/dbt-requirements.txt \
    && chown -R airflow: /opt/dbt-venv

ENV DATAFORGE_DBT_BIN=/opt/dbt-venv/bin/dbt

USER airflow
