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
        except:
            print(ts() + " - connecting to the DDBB")

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
    with open(my_file, "r") as the_file:
        return json.load(the_file)

# retrieve user from a saved session or by triggering a request to the bridge
def get_user():
    # check for a credential file
    if not path.exists(CRED_FILE_PATH):
        while True:
            try:
                username = create_new_username(BRIDGE_IP)
                break
            except QhueException as err:
                print(ts() + " - Error while creating a new user name: {0}".format(err))
        with open(CRED_FILE_PATH, "w") as cred_file:
            cred_file.write(username)
    else:
        with open(CRED_FILE_PATH, "r") as cred_file:
            username = json.load(cred_file)
    return username["hue"]

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
    meas['berlin_temperature'] = r['current_observation']['temp_c']
    meas['berlin_humidity'] = r['current_observation']['relative_humidity']
    meas['berlin_temperature_feels'] = r['current_observation']['feelslike_c']
    
    weather_state = r['current_observation']['weather']

    if weather_state in wunderground_states:
        print(ts() + " - weather is " + weather_state + " now {0}C ({2}C) and {1}".format(meas['berlin_temperature'],
            meas['berlin_humidity'], meas['berlin_temperature_feels']))
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
    bridge = Bridge(config['bridge'], get_user())

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