FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ARG SAM2_REVISION=2b90b9f5ceec907a1c18123530e92e794ad901a4
ARG SAM2_CHECKPOINT_URL=https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt
ARG SAM2_CHECKPOINT_SHA256=6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SAM2_BUILD_CUDA=0 \
    SEGMENTER_CHECKPOINT=/opt/models/sam2.1_hiera_small.pt

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && git clone https://github.com/facebookresearch/sam2.git /opt/sam2 \
    && git -C /opt/sam2 checkout "$SAM2_REVISION" \
    && pip install --no-cache-dir --no-deps /opt/sam2 \
    && mkdir -p /opt/models \
    && curl --fail --location "$SAM2_CHECKPOINT_URL" --output "$SEGMENTER_CHECKPOINT" \
    && echo "$SAM2_CHECKPOINT_SHA256  $SEGMENTER_CHECKPOINT" | sha256sum --check -

COPY . .

EXPOSE 8100

CMD ["gunicorn", "--bind", "0.0.0.0:8100", "--timeout", "120", "--workers", "1", "--threads", "4", "--access-logfile", "-", "manage:app"]
