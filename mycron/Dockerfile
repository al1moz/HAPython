ARG BUILD_FROM
#FROM ghcr.io/home-assistant/amd64-base-debian
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG BIN_VERSION=v0.0.28

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y -q --install-recommends --no-install-suggests \
    tzdata python3 python3-pip python3-serial python3-influxdb python3-paho-mqtt python3-requests && \
    pip3 install --no-cache-dir --break-system-packages influxdb-client && \
    apt-get purge -y --auto-remove python3-pip && \
    rm -rf /var/lib/apt/lists/* /root/.cache

#RUN pip install pyserial influxdb paho.mqtt
COPY root /
WORKDIR /
