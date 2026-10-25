# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 BARD_DATA_DIR=/data BARD_HOST=0.0.0.0
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

EXPOSE 8090
# The voice is downloaded into the /data volume on first start; later starts reuse it (and still boot offline).
CMD ["sh", "-c", "python -m piper.download_voices \"${BARD_VOICE:-en_US-lessac-medium}\" --download-dir /data/voices; exec python -m src.run"]
