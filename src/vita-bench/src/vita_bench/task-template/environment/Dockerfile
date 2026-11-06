FROM python:3.12-slim

# Main (agent) container. It also hosts the verifier, which needs the official
# VitaBench package to run the rubric evaluator, so install VitaBench here too.

ARG VITABENCH_REPO="https://github.com/meituan-longcat/vitabench.git"
ARG VITABENCH_COMMIT="742e240855bf8686a0842360749d5ea970ea3987"

ENV VITABENCH_ROOT=/opt/vitabench
ENV VITA_MODEL_CONFIG_PATH=/opt/vita_models.yaml
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git clone "${VITABENCH_REPO}" "${VITABENCH_ROOT}" \
    && git -C "${VITABENCH_ROOT}" checkout "${VITABENCH_COMMIT}" \
    && rm -rf "${VITABENCH_ROOT}/.git" \
    && pip install --no-cache-dir -e "${VITABENCH_ROOT}" \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

# vita.config imports models.yaml at import time; a placeholder keeps imports
# working until the verifier regenerates it from the environment variables.
RUN printf 'default:\n  base_url: ""\n  headers: {}\nmodels: []\n' > "${VITA_MODEL_CONFIG_PATH}"
