#!/usr/bin/env python3

import os
import time
from datetime import datetime
import random
from influxdb import InfluxDBClient
from paho.mqtt import client as mqtt_client


broker = '192.168.252.4'
port = 1883
#topic = "shellies/shellyem1/emeter/1/power"
# generate client ID with pub prefix randomly
client_id = f'python-mqtt-{random.randint(0, 100)}'
username = 'mqtt'
password = os.environ.get('PASSWORDMQTT')

# connexion a la base de données InfluxDB
DB_SERVER = '192.168.252.4'
DB_PORT = '8086'
DB_DATABASE = 'teleinfo2'

CLIENT = InfluxDBClient(DB_SERVER, DB_PORT)
CONNECTED = False
while not CONNECTED:
    try:
        if {'name': DB_DATABASE} not in CLIENT.get_list_database():
            CLIENT.create_database(DB_DATABASE)
        CLIENT.switch_database(DB_DATABASE)
        print("Connected to influxDB")
    except requests.exceptions.ConnectionError:
        print('InfluxDB is not reachable. Waiting 5 seconds to retry.')
        time.sleep(5)
    else:
        CONNECTED = True

def connect_mqtt() -> mqtt_client:
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
        else:
            print("Failed to connect, return code %d\n", rc)

    client = mqtt_client.Client(client_id)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.connect(broker, port)
    return client


def subscribe(client: mqtt_client):
    def on_message(client, userdata, msg):
        #print(f"Received `{msg.payload.decode()}` from `{msg.topic}` topic")
        trame = dict()
        topicArr = msg.topic.split('/')
        keyTopic = topicArr[1]+'_'+topicArr[3]
        trame[keyTopic.upper()] = float(msg.payload.decode())
        trame["timestamp"] = int(time.time())
        add_measures(trame)

    client.subscribe('shellies/shellyem1/emeter/0/power')
    client.subscribe('shellies/shellyem1/emeter/1/power')
    client.subscribe('shellies/shellyem2/emeter/0/power')
    client.subscribe('shellies/shellyem2/emeter/1/power')
    client.subscribe('shellies/shellyem3/emeter/0/power')
    client.subscribe('shellies/shellyem3/emeter/1/power')
    client.subscribe('shellies/shellyem4/emeter/0/power')
    client.subscribe('shellies/shellyem4/emeter/1/power')
    client.on_message = on_message


def run():
    client = connect_mqtt()
    subscribe(client)
    client.loop_forever()

def add_measures(measures):
    """Add measures to array."""
    points = []
    for measure, value in measures.items():
        point = {
            "measurement": measure,
            "tags": {
                # identification de la sonde et du compteur
                "host": "raspberry",
                "region": "shellyem"
            },
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fields": {
                "value": abs(value)
                }
            }
        points.append(point)

    CLIENT.write_points(points)


if __name__ == '__main__':
    run()

