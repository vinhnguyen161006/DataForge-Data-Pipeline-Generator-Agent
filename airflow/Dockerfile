FROM ghcr.io/astral-sh/uv:0.10.10@sha256:cbe0a44ba994e327b8fe7ed72beef1aaa7d2c4c795fd406d1dbf328bacb2f1c5 AS uv

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
