#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import json
import time
import signal
import gevent
import requests
import threading
import datetime
from os import path
import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
from qhue import Bridge, QhueException, create_new_username

# hard-coded constants
SETTINGS_FILE_PATH  = "settings.json"
CONFIG_FILE_PATH    = "config.json"
WUNDERGROUND_PATH   = "wunderground.json"
CRED_FILE_PATH      = ".philips_hue_secret.json"
OVERRIDE_PERIOD     = 15.0
WUNDERGROUND_PERIOD = 300.0

DDDBB_NAME          = "local"
DDBB_ADDRESS        = "localhost"
DDBB_PORT           = 8086
BROKER_ADDRESS      = "localhost"
BROKER_PORT         = 1883

# global values and objects
bridge       = None
lights       = None
influxClient = None
client       = None

# return timestamp as string
def ts():
    return str(datetime.datetime.now())

def on_connect(client, userdata, flag, rc):
    client.subscribe("local/#")

def on_message(client, userdata, msg):
    pass

# connects to the influxDB database
def connect_to_ddbb():
    global influxClient
    while True:
        try:
            time.sleep(5)
            influxClient = InfluxDBClient(DDBB_ADDRESS, DDBB_PORT, "root", "root")
            influxClient.create_database(DDDBB_NAME)
            break
        except Exception as e:
            print(ts() + str(e))

# publish to the influxDB database
def publish_to_database(values):
    global influxClient

    data = []
    # takes an array of dictionaries and builds a list
    for key, val in values.iteritems():
        data.append({
            'measurement': key,
            'fields': {'value': val }
            })
        influxClient.write_points(data, database=DDDBB_NAME, time_precision="ms")
        data = []

# JSON file retriever
def get_file(my_file):
    if not path.exists(my_file):
        SystemExit(ts() + " - No settings given, exiting!")
    try:
        with open(my_file, "r") as the_file:
            return json.load(the_file)
    except Exception as e:
        SystemExit(ts() + str(e))

# retrieve user from a saved session
def get_user():
    # check for a credential file
    if not path.exists(CRED_FILE_PATH):
        SystemExit(ts() + " - HUE user not enabled")
    else:
        with open(CRED_FILE_PATH, "r") as cred_file:
            username = json.load(cred_file)
            return username["hue"]
    return None

# change lights from the default value when on to a preferred one
def override_default_values():
    global lights
    settings = get_file(SETTINGS_FILE_PATH)

    t = threading.Timer(OVERRIDE_PERIOD, override_default_values)
    t.daemon = True
    t.start()

    try:
        for key, value in lights().iteritems():
            # print key, value
            for room, config in settings.iteritems():
                if room in value['name'] and \
                    value['state']['reachable'] and value['state']['on']:
                    # check for the default values
                    # note: the light bulbs with type "Extended color light" have a richer
                    # set of features, thus why we evaluate separately the attributes for these,
                    # namely "hue", "sat", "xy" (colormode for type "Color temperature light" only
                    # allows "ct")
                    args = {}
                    for x, y in config['unwanted'].iteritems():
                        if x in value['state'] and value['state'][x] == y:
                            args[x] = config['default'][x]
                    if args:
                        # if one or more attributes in "unwanted" are the same as in "default",
                        # it will always end in here, for those cases it would be better to avoid
                        # these values in the settings.json file
                        print(ts() + " - unwanted values for {0} (at {1}) -> setting back".format(room, key))
                        lights[key].state(**args)
    except Exception as err:
        SystemExit(ts() + " - light bulbs application crashed due to {0}".format(err))

# check the current temperature and climate conditions in my city
# and update my lights
def lights_weather_indication():
    global bridge, ligths

    t = threading.Timer(WUNDERGROUND_PERIOD, lights_weather_indication)
    t.daemon = True
    t.start()

    wunderground_states = get_file(WUNDERGROUND_PATH)
    wunderground_api = get_file(CRED_FILE_PATH)
    wunderground_url = 'http://api.wunderground.com/api/{0}/geolookup/conditions/q'.format(wunderground_api['wunderground'])

    r = requests.get(wunderground_url + '/pws:IBERLIN1449.json').json()

    # build my dictionary array to write to database
    meas = {}
    meas['berlin_temperature'] = round(float(r['current_observation']['temp_c']), 2)
    meas['berlin_humidity'] = round(float(r['current_observation']['relative_humidity'][:-1]), 2)
    meas['berlin_temperature_feels'] = round(float(r['current_observation']['feelslike_c']), 2)
    meas['weather_state'] = r['current_observation']['weather']
    meas['berlin_pressure'] = round(float(r['current_observation']['pressure_mb']), 2)
    meas['berlin_wind_speed_kph'] = round(float(r['current_observation']['wind_kph']), 2)
    meas['berlin_wind_gust_kph'] = round(float(r['current_observation']['wind_gust_mph']) * 1.609344, 2)

    if meas['weather_state'] in wunderground_states:
        print(ts() + " - weather is {0} now {1}C ({2}C) and {3}%RH".format(meas['weather_state'],
            meas['berlin_temperature'], meas['berlin_temperature_feels'], meas['berlin_humidity']))
        publish_to_database(meas)

# set the schedules and ignore the ones created by the other applications and accessories
def lights_schedule():
    schedules = bridge.schedules
    print(schedules())

    # check if a schedule exists, if not create one
    pass

# set the rules and ignore the ones created by the other applications and accessories
def lights_rule():
    rules = bridge.rules
    print(rules())

    # check if a schedule exists, if not create one
    pass

# in case of termination signal exit
def stop_application():
    sys.exit(0)

def main():
    global bridge, lights, influxClient, client

    # create the bridge resource, passing the captured user name
    config = get_file(CONFIG_FILE_PATH)
    user = get_file(CRED_FILE_PATH)
    bridge = Bridge(config['bridge'], user['hue'])

    # create a lights resource
    lights = bridge.lights

    # MQTT local broker
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_ADDRESS, BROKER_PORT)

    # connect to the database
    connect_to_ddbb()

    # start my threads
    override_default_values()
    lights_weather_indication()
    # lights_schedule()
    # lights_rule()

    while(True):
        time.sleep(0.5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_application()