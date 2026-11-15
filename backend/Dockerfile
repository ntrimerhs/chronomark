# ChronoMark backend: FastAPI + ffmpeg, with Qdrant Cloud and Cloudflare R2
# reached over the network from backend/.env (nothing vector- or video-related
# is stored in the image or on the container's disk beyond derived artifacts).
#
# Python 3.12 (wheels for torch/transformers are the most reliable here) with
# ffmpeg from apt, since yt-dlp, audio extraction and frame grabs all shell
# out to the ffmpeg binary.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Model caches (MiniLM, CLIP) live in a named volume, not in the image,
    # so they survive rebuilds and are downloaded exactly once.
    HF_HOME=/cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:${PATH}"

COPY requirements.txt ./

# torch first, pinned to CPU wheels: on Linux the plain `pip install torch`
# pulls the CUDA build with all the NVIDIA libraries, which is several GB
# the backend never uses. Installing it first means the `torch` line in
# requirements.txt is then already satisfied.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

# The code last: any edit rebuilds this thin layer in seconds.
COPY . .

# The app can take a while to answer the first request (model warmup at
# startup), so the healthcheck gets a long grace period.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=4)" || exit 1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
