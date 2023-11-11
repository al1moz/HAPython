ARG BUILD_FROM
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG BIN_VERSION=v0.0.28

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y -q --install-recommends --no-install-suggests tzdata python3 && \
    rm -rf /var/lib/apt/lists/*

# Créez un répertoire de travail dans le conteneur
WORKDIR /

# Installez les modules nécessaires
RUN pip install pyserial influxdb paho.mqtt

# Copiez votre script Python dans le conteneur
COPY root /


# Commande par défaut à exécuter lorsque le conteneur démarre
#CMD ["python3", "teleinfo_standard.py"]
