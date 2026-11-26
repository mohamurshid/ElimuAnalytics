# Backend image: FastAPI + the IRT engine + the curriculum embedder.
# Build from the repository root:  docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models

WORKDIR /srv

# CPU-only torch first. sentence-transformers would otherwise pull the CUDA
# build, several gigabytes of libraries a server without a GPU never loads.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r backend/requirements.txt

# Bake the embedding model into the image, so a restart never waits on a
# download and the server needs no outbound access to Hugging Face.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# The app resolves data/ and frontend/legacy/ relative to the repository
# root (parents[2] of backend/app/), so the same layout is kept here.
COPY alembic.ini ./
COPY backend/alembic backend/alembic
COPY backend/app backend/app
COPY data/kicd/kicd_curriculum_chunks_full.json data/kicd/
COPY frontend/legacy frontend/legacy

RUN useradd --system --uid 10001 elimu && chown -R elimu /opt/models
USER elimu
WORKDIR /srv/backend

EXPOSE 8000
# --proxy-headers: Caddy terminates HTTPS, so the scheme the browser used
# arrives in X-Forwarded-Proto. One worker: the embedder is ~500 MB per process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
