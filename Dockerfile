# Immutable Python index used by the qualified AMD64 image (3.14.8).
# The explicit platform also prevents legacy builders selecting their ARM host.
FROM --platform=linux/amd64 python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS qualified
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

FROM --platform=linux/amd64 python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS lite
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
COPY --from=qualified /app/qualification/heidi12-reference.json qualification/heidi12-reference.json
COPY --from=qualified /app/qualification/qualify_compact.py qualification/qualify_compact.py
COPY --from=qualified /app/qualification/qualify_hosted_compact.py qualification/qualify_hosted_compact.py
COPY --from=qualified /app/qualification/compact-reference.json qualification/compact-reference.json
COPY --from=qualified /app/qualification/compact-reference-heidi12.json qualification/compact-reference-heidi12.json
ENV PYTHONPATH=/app/engine/src:/app/ai PYTHONDONTWRITEBYTECODE=1 \
    TUPPI_HOSTED_BOT_LEVEL=lite TUPPI_HOSTED_HEIDI10=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# These checks execute inside the final, PyTorch-free filesystem: plain lite, Nelli 1.0
# and 1.1, and the compact controller in modes 2 (Heidi 1.1) and 4 (Heidi 1.2).
RUN python qualification/qualify_lite.py \
    && python qualification/qualify_heidi.py \
    && python qualification/qualify_compact.py --no-torch --report qualification/compact-result.json \
    && python qualification/qualify_compact.py --no-torch --mode 4 --reference qualification/compact-reference-heidi12.json \
         --report qualification/compact-heidi12-result.json \
    && groupadd --gid 10001 tuppi && useradd --uid 10001 --gid tuppi --no-create-home tuppi \
    && chmod +x start.sh
# TUPPI_CLIENT_IP_HEADER: Render is behind Cloudflare, which sets the client
# address in this header; per-client rate limits fall back to the global ones
# without it.
ENV TUPPI_WEB_DIR=/app/web TUPPI_SERVER_DATA_DIR=/data/rooms \
    TUPPI_SERVER_RULESET=project_target_v3 TUPPI_SERVER_AI_PROFILE=tuppi_ai_search_v1 \
    TUPPI_HOSTED_BOT=1 TUPPI_SERVER_REVIEW=0 TUPPI_SERVER_SOOLI_ODDS=0 \
    TUPPI_CONTRACT_ROLLOUT_SAMPLES=0 TUPPI_CLIENT_IP_HEADER=cf-connecting-ip
EXPOSE 10000
CMD ["/app/start.sh"]
