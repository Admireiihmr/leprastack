FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 libgl1 git \
    build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces runs as user 1000
RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
# Install torch first (needed to compile mmcv ops)
RUN pip install --no-cache-dir torch>=2.1 torchvision>=0.16 numpy>=1.24,\<2.0
# Force-compile mmcv from source with C extensions (needed by mmpose)
RUN MMCV_WITH_OPS=1 FORCE_CUDA=0 pip install --no-cache-dir --no-binary=mmcv "mmcv>=2.0.0rc4,<2.2.0"
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# gdown for Google Drive checkpoint downloads (>=5.0 needed for --remaining-ok flag in start.sh)
RUN pip install --no-cache-dir "gdown>=5.0"

COPY . .

# Ensure writable directories
RUN mkdir -p web_runs samples checkpoints \
    && chown -R user:user /app/web_runs /app/samples /app/checkpoints

RUN chmod +x start.sh

USER user

EXPOSE 7860

CMD ["bash", "start.sh"]
