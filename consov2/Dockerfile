ARG BUILD_FROM
FROM $BUILD_FROM

# Uniquement des paquets Debian : pas de pip, pas de compilation.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-serial python3-paho-mqtt tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod a+x /etc/services.d/consov2/run /etc/services.d/consov2/finish
WORKDIR /app
