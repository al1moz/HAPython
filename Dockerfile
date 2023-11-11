ARG BUILD_FROM
#FROM ghcr.io/home-assistant/amd64-base-debian
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG BIN_VERSION=v0.0.28

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y -q --install-recommends --no-install-suggests tzdata python3 \
    python3-serial python3-influxdb python3-paho-mqtt && \
    rm -rf /var/lib/apt/lists/*

#RUN pip install pyserial influxdb paho.mqtt
COPY root /
WORKDIR /
