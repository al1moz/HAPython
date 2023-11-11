#!/usr/bin/env python
import os
from influxdb import InfluxDBClient
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

#valeur par defaut
q1=q2=q3=q4=q5=q6=q7=q8 = '0'

#InfluxDB
CLIENT = InfluxDBClient('localhost', 8086)
CLIENT.switch_database('teleinfo2')
query = 'SELECT "value"  / 1000 as cindex FROM "EASF01" ORDER BY time DESC LIMIT 1'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    cindex = str(item['cindex'])

#Shelly1_0
query = 'SELECT mean(value) FROM SHELLYEM1_0 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q1 = str(round(item['mean']))

#Shelly1_1
query = 'SELECT mean(value) FROM SHELLYEM1_1 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q2 = str(round(item['mean']))

#Shelly2_0
query = 'SELECT mean(value) FROM SHELLYEM2_0 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q3 = str(round(item['mean']))

#Shelly2_1
query = 'SELECT mean(value) FROM SHELLYEM2_1 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q4 = str(round(item['mean']))

#Shelly3_0
query = 'SELECT mean(value) FROM SHELLYEM3_0 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q5 = str(round(item['mean']))

#Shelly3_1
query = 'SELECT mean(value) FROM SHELLYEM3_1 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q6 = str(round(item['mean']))

#Shelly4_0
query = 'SELECT mean(value) FROM SHELLYEM4_0 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q7 = str(round(item['mean']))

#Shelly4_1
query = 'SELECT mean(value) FROM SHELLYEM4_1 where time >= now()-6m and time <= now()-1m'
result = CLIENT.query(query)
points = result.get_points()
for item in points:
    q8 = str(round(item['mean']))

try:
    print('cindex='+cindex+'&q1='+q1+'&q2='+q2+'&q3='+q3+'&q4='+q4+'&q5='+q5+'&q6='+q6+'&q7='+q7+'&q8='+q8)
    req = urlopen('https://conso.ctrl.ovh/bin/receiver.php?cindex='+cindex+'&q1='+q1+'&q2='+q2+'&q3='+q3+'&q4='+q4+'&q5='+q5+'&q6='+q6+'&q7='+q7+'&q8='+q8, data=None)
    print(req.read())
except HTTPError as e:
    # do something
    print('Error code: ', e.code)
except URLError as e:
    # do something (set req to blank)
    print('Reason: ', e.reason)
