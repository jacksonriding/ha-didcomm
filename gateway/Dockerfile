FROM python:3.12-slim AS gateway

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

FROM ghcr.io/openwallet-foundation/acapy-agent:py3.13-1.6-lts AS addon

USER root
WORKDIR /app/gateway

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64
LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENTRYPOINT ["python", "addon.py"]
