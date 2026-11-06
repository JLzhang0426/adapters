FROM python:3.12-slim

# Runtime sidecar: hosts the VitaBench environment (tools + database) and the
# simulated user behind an MCP streamable-http server.

ARG VITABENCH_REPO="https://github.com/meituan-longcat/vitabench.git"
ARG VITABENCH_COMMIT="742e240855bf8686a0842360749d5ea970ea3987"

ENV VITABENCH_ROOT=/opt/vitabench
ENV VITA_MODEL_CONFIG_PATH=/app/vita_models.yaml
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git clone "${VITABENCH_REPO}" "${VITABENCH_ROOT}" \
    && git -C "${VITABENCH_ROOT}" checkout "${VITABENCH_COMMIT}" \
    && rm -rf "${VITABENCH_ROOT}/.git" \
    && pip install --no-cache-dir -e "${VITABENCH_ROOT}" "fastmcp>=3.0" \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

COPY vita_models_config.py server.py task_config.json ./

EXPOSE 8000

CMD ["python3", "server.py"]
