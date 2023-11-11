#!/usr/bin/python
# Version 0.1
# https://github.com/cyrilpawelko/arkteos_reg3

import socket
import time
import os
from datetime import datetime
import sys
import paho.mqtt.client as mqtt

HOST = '192.168.252.152'
PORT = 9641
MQTT_HOST = "192.168.252.4"
MQTT_BASE_TOPIC = "arkteos/reg3/"   # don't forget the trailing slash

MQTT_HOST = '192.168.252.4'
MQTT_PORT = 1883
USERNAME = 'mqtt'
PASSWORD = os.environ.get('PASSWORDMQTT')

decoder = [
    { 'stream' : 227, 'name' : 'primaire_pression' ,'descr' : 'Pression eau primaire', 'byte1': 62, 'weight1': 1, 'byte2': 0, 'weight2': 0, 'divider': 10 },
    { 'stream' : 227, 'name' : 'externe_pression' ,'descr' : 'Pression eau extérieure', 'byte1': 46, 'weight1': 1, 'byte2': 0, 'weight2': 0, 'divider': 10 },
    { 'stream' : 227, 'name' : 'primaire_temp_eau_aller' ,'descr' : 'Température eau primaire aller', 'byte1': 54, 'weight1': 1, 'byte2': 55, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'primaire_temp_eau_retour' ,'descr' : 'Température eau primaire retour', 'byte1': 56, 'weight1': 1, 'byte2': 57, 'weight2': 256, 'divider': 10 },
    { 'stream' : 163, 'name' : 'exterieur_temp' ,'descr' : 'Température extérieure', 'byte1': 24, 'weight1': 1, 'byte2': 25, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'zone1_temp_interieur' ,'descr' : 'Température intérieur zone 1', 'byte1': 68, 'weight1': 1, 'byte2': 69, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'zone2_temp_interieur' ,'descr' : 'Température intérieur zone 2', 'byte1': 88, 'weight1': 1, 'byte2': 89, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'zone1_consigne' ,'descr' : 'Consigne intérieure zone 1', 'byte1': 70, 'weight1': 1, 'byte2': 71, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'zone2_consigne' ,'descr' : 'Consigne intérieure zone 2', 'byte1': 90, 'weight1': 1, 'byte2': 91, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'ecs_temp_eau_milieu' ,'descr' : 'Température ballon ECS milieu', 'byte1': 108, 'weight1': 1, 'byte2': 109, 'weight2': 256, 'divider': 10 },
    { 'stream' : 227, 'name' : 'ecs_temp_eau_bas' ,'descr' : 'Température ballon ECS bas', 'byte1': 110, 'weight1': 1, 'byte2': 111, 'weight2': 256, 'divider': 10 },
]


def main():
    stream_received = { 
        163 : False, 
        227 : False 
    }

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    CONNECTED = False
    mqtt_client = mqtt_client.Client('arkteos.py')
    mqtt_client.username_pw_set(username, password)
    mqtt_client.on_connect = on_connect
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    except:
        print("Arkteos Error: MQTT connection failed")

    while not CONNECTED : # Wait for connection to be available, sometimes one or two minutes
        try :
            client.connect((HOST, PORT))
            CONNECTED = True
        except socket.error as e:
            print("Connection failed (%s), waiting" % e)
            time.sleep(3)
    print('Arkteos Connection to ' + HOST + ':' + str(PORT) + ' successfull.')

    while not ( stream_received[163] and stream_received[227] ):
        data_lenght = 0
        try :
            data = client.recv(1024)
            data_lenght = len(data)
        except KeyboardInterrupt:
            pass
        #print('Received %s octets' %data_lenght)
        
        data_lenght = len(data)
        stream_received[data_lenght] = True

        #Collecte data
        for item in ( x for x in decoder if x["stream"] == data_lenght) :
            if item['byte2']==0 :
                item_value=(data[item['byte1']]*item['weight1'])/item['divider']
            else :
                item_value=(data[item['byte1']]*item['weight1']+data[item['byte2']]*item['weight2'])/item['divider']
            #print('%s:%.1f, ' % (item['name'], item_value),end='')
            print(datetime.utcnow().strftime("%H:%M:%S"),':',MQTT_BASE_TOPIC + item['name'],':', item_value)
            mqtt_client.publish(MQTT_BASE_TOPIC + item['name'], item_value)
        #print('')

    client.shutdown(socket.SHUT_RDWR)
    client.close()

if __name__ == '__main__':
    while True:
        main()
        time.sleep(300)