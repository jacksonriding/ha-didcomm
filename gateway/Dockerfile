FROM python:3.15-slim AS gateway

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ha_didcomm ./ha_didcomm

CMD ["python", "-m", "ha_didcomm.serve"]

FROM ghcr.io/openwallet-foundation/acapy-agent:py3.13-1.7.1rc0@sha256:8d6e053a7c74016cd0bfecd0ba971f935d0ddb4f759a3ffcfd65d466ce1a0170 AS addon

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
