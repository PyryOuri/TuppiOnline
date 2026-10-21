FROM python:3.14-slim-bookworm AS qualified
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libopenblas-dev gosu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
COPY engine engine
COPY ai ai
COPY qualification qualification
ENV PYTHONPATH=/app/engine/src:/app/ai OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    TUPPI_HOSTED_BOT_LEVEL=full
RUN sh ai/native/build.sh --blas && python qualification/qualify.py
COPY web web
COPY start.sh .
RUN groupadd --gid 10001 tuppi && useradd --uid 10001 --gid tuppi --no-create-home tuppi \
    && chmod +x start.sh
ENV TUPPI_WEB_DIR=/app/web TUPPI_SERVER_DATA_DIR=/data/rooms \
    TUPPI_SERVER_RULESET=project_target_v3 TUPPI_SERVER_AI_PROFILE=tuppi_ai_search_v1 \
    TUPPI_HOSTED_BOT=1 TUPPI_SERVER_REVIEW=0 TUPPI_SERVER_SOOLI_ODDS=0 \
    TUPPI_CONTRACT_ROLLOUT_SAMPLES=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
EXPOSE 10000
CMD ["/app/start.sh"]

# Retain the full-search runtime and all frozen qualification inputs explicitly.
FROM qualified AS full

# Copy only the verified lite server package from the qualified build stage.
FROM qualified AS lite-package
RUN python qualification/package_lite.py

FROM python:3.14-slim-bookworm AS lite
RUN apt-get update && apt-get install -y --no-install-recommends libopenblas0-pthread gosu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=qualified /app/engine engine
COPY --from=lite-package /app/lite-ai ai
COPY --from=qualified /app/web web
COPY --from=qualified /app/start.sh .
COPY --from=qualified /app/qualification/result.json qualification/builder-result.json
COPY --from=qualified /app/qualification/lite-reference.json qualification/lite-reference.json
COPY --from=qualified /app/qualification/qualify_lite.py qualification/qualify_lite.py
COPY --from=qualified /app/qualification/qualify_heidi.py qualification/qualify_heidi.py
COPY --from=qualified /app/qualification/heidi-reference.json qualification/heidi-reference.json
ENV PYTHONPATH=/app/engine/src:/app/ai PYTHONDONTWRITEBYTECODE=1 \
    TUPPI_HOSTED_BOT_LEVEL=lite OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# This check executes inside the final, PyTorch-free filesystem.
RUN python qualification/qualify_lite.py \
    && python qualification/qualify_heidi.py \
    && groupadd --gid 10001 tuppi && useradd --uid 10001 --gid tuppi --no-create-home tuppi \
    && chmod +x start.sh
ENV TUPPI_WEB_DIR=/app/web TUPPI_SERVER_DATA_DIR=/data/rooms \
    TUPPI_SERVER_RULESET=project_target_v3 TUPPI_SERVER_AI_PROFILE=tuppi_ai_search_v1 \
    TUPPI_HOSTED_BOT=1 TUPPI_SERVER_REVIEW=0 TUPPI_SERVER_SOOLI_ODDS=0 \
    TUPPI_CONTRACT_ROLLOUT_SAMPLES=0
EXPOSE 10000
CMD ["/app/start.sh"]
