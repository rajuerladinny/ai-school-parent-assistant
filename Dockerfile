# Public demo image (fictional data only). Used for the Hugging Face Space and `docker run`.
#   docker build -t school-parent-assistant .
#   docker run -p 7860:7860 school-parent-assistant
# Then open http://localhost:7860
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# CPU-only PyTorch keeps the image small; sentence-transformers would otherwise pull CUDA builds.
COPY requirements.txt requirements-rag.txt ./
RUN pip install --upgrade pip \
 && pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements-rag.txt

USER user
ENV HOME=/home/user \
    HF_HOME=/home/user/.cache/huggingface

# Download the embedding model at build time so the first visitor doesn't wait for it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY --chown=user app ./app
COPY --chown=user docs/demo ./docs/demo

# Public demo settings. The admin key is published on purpose: demo mode makes the
# staff portal read-only. The database lives in /tmp, so every restart starts fresh.
ENV SCHOOL_DEMO_MODE=1 \
    SCHOOL_ADMIN_KEY=sunrise-demo-admin-key \
    SCHOOL_DB=/tmp/school-demo.db \
    RAG_VECTOR_PATH=/tmp/chroma-demo \
    PORT=7860

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
