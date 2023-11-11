# Utilisez une image de base avec Python
FROM python:3

# Créez un répertoire de travail dans le conteneur
WORKDIR /app

# Installez les modules nécessaires
RUN pip install pyserial influxdb paho.mqtt

# Copiez votre script Python dans le conteneur
COPY root /


# Commande par défaut à exécuter lorsque le conteneur démarre
#CMD ["python3", "teleinfo_standard.py"]
