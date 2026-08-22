FROM python:3.14-slim AS gateway

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ha_didcomm ./ha_didcomm

CMD ["python", "-m", "ha_didcomm.serve"]

FROM ghcr.io/openwallet-foundation/acapy-agent:py3.13-1.6-lts AS addon

USER root
WORKDIR /app/gateway

RUN apt-get update \
    && apt-get install --no-install-recommends -y nginx \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY src/ha_didcomm ./ha_didcomm

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64
LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENTRYPOINT ["python", "-m", "ha_didcomm.addon"]
