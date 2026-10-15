# ---- Build stage: compile native dependencies and build the venv ----
FROM ubuntu:26.04 AS builder

RUN apt update && apt -y install --no-install-recommends \
  git \
  ca-certificates \
  python3 \
  python3-dev \
  build-essential \
  cmake \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/
ENV CFLAGS="-I/opt/pillow-include"
ENV UV_PYTHON_DOWNLOADS=never

WORKDIR /planesign

# Only the dependency manifests, so source changes reuse the cached venv (and the rgbmatrix compile).
COPY pyproject.toml uv.lock .python-version ./

# rgbmatrix's SetImage reads Pillow's C image struct directly, so it must be compiled against the
# headers of the Pillow that the venv runs (uv.lock), not Ubuntu's python3-pil: that is a different
# version, and its package omits Mode.h.
RUN python3 - <<'EOF'
import hashlib, io, tarfile, tomllib, urllib.request
pillow = next(p for p in tomllib.load(open("uv.lock", "rb"))["package"] if p["name"] == "pillow")
sdist = pillow["sdist"]
data = urllib.request.urlopen(sdist["url"], timeout=120).read()
if "sha256:" + hashlib.sha256(data).hexdigest() != sdist["hash"]:
    raise SystemExit(f"Pillow {pillow['version']} sdist does not match the uv.lock hash")
with tarfile.open(fileobj=io.BytesIO(data)) as tar:
    headers = [m for m in tar.getmembers() if m.isfile() and "/src/libImaging/" in m.name and m.name.endswith(".h")]
    for member in headers:
        member.name = member.name.rsplit("/", 1)[1]
    tar.extractall("/opt/pillow-include", members=headers, filter="data")
print(f"Installed {len(headers)} Pillow {pillow['version']} headers")
EOF

RUN uv sync --frozen --no-install-project --no-dev

# ---- Runtime stage: only what is needed to run the sign ----
FROM ubuntu:26.04

RUN apt update && apt -y install --no-install-recommends \
  nginx \
  openssl \
  ca-certificates \
  curl \
  python3 \
  libpython3.14 \
  mpg123 \
  alsa-utils \
  && apt clean \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

# Application source and the pre-built virtual environment
COPY . .
COPY --from=builder /planesign/.venv /planesign/.venv
# For the devcontainer, whose own `uv sync` rebuilds rgbmatrix (see CFLAGS in devcontainer.json).
COPY --from=builder /opt/pillow-include /opt/pillow-include

# Nginx Setup
RUN unlink /etc/nginx/sites-enabled/default
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"

# Define build argument with default value
ARG PLANESIGN_ROOT=/planesign

# Copy and substitute nginx config using the build arg directly
COPY docker_nginx_planesign.conf /etc/nginx/conf.d/
RUN sed -i "s|\${PLANESIGN_ROOT}|${PLANESIGN_ROOT}|g" /etc/nginx/conf.d/docker_nginx_planesign.conf

ARG BUILD_VERSION=argnotset
RUN echo ${BUILD_VERSION} > version.txt

CMD ["sh", "-c", "service nginx start && .venv/bin/python planesign/"]
