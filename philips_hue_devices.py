#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import yaml
import time
import signal
import gevent
import requests
import threading
import datetime
import logging
import logging.config
from os import path
import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
from qhue import Bridge, QhueException, create_new_username

# hard-coded constants
SETTINGS_FILE_PATH  = "settings.json"
CONFIG_FILE_PATH    = "config.json"
OPENWEATHER_PATH    = "openweather.json"
CRED_FILE_PATH      = ".philips_hue_secret.json"
OVERRIDE_PERIOD     = 15.0
OPENWEATHER_PERIOD  = 600.0
OPENWEATHER_URL     = '/weather?id=2950159'
LOGGING_PATH        = 'weather_log_config.yaml'

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

with open(os.path.join(os.path.dirname(__file__), LOGGING_PATH)) as f:
    config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)
logger = logging.getLogger(__name__)

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
            logger.exception(e)

# publish to the influxDB database
def publish_to_database(values):
    global influxClient

    data = []
    # takes an array of dictionaries and builds a list
    for key, val in values.items():
        data.append({
            'measurement': key,
            'fields': {'value': val }
            })
        influxClient.write_points(data, database=DDDBB_NAME, time_precision="ms")
        data = []

# JSON file retriever
def get_file(my_file):
    file_loc = os.path.join(os.path.dirname(__file__), my_file)
    if not path.exists(file_loc):
        logger.error("no settings found")
        SystemExit(ts() + " - No settings given, exiting!")
    try:
        with open(file_loc, "r") as the_file:
            return json.load(the_file)
    except Exception as e:
        logger.exception(e)
        SystemExit(ts() + str(e))

# retrieve user from a saved session
def get_user():
    file_loc = os.path.join(os.path.dirname(__file__), CRED_FILE_PATH)
    if not path.exists(file_loc):
        logger.error("HUE user not enabled")
        SystemExit(ts() + " - HUE user not enabled")
    else:
        with open(file_loc, "r") as cred_file:
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
        for key, value in lights().items():
            # print key, value
            for room, config in settings.items():
                if room in value['name'] and \
                    value['state']['reachable'] and value['state']['on']:
                    # check for the default values
                    # note: the light bulbs with type "Extended color light" have a richer
                    # set of features, thus why we evaluate separately the attributes for these,
                    # namely "hue", "sat", "xy" (colormode for type "Color temperature light" only
                    # allows "ct")
                    args = {}
                    for x, y in config['unwanted'].items():
                        if x in value['state'] and value['state'][x] == y:
                            args[x] = config['default'][x]
                    if args:
                        # if one or more attributes in "unwanted" are the same as in "default",
                        # it will always end in here, for those cases it would be better to avoid
                        # these values in the settings.json file
                        logger.error(ts() + " - unwanted values for {0} (at {1}) -> setting back".format(room, key))
                        lights[key].state(**args)
    except Exception as err:
        logger.exception(err)
        SystemExit(ts() + " - light bulbs application crashed due to {0}".format(err))

# check the current temperature and climate conditions in my city
# and update my lights
def lights_weather_indication():
    global bridge, ligths

    t = threading.Timer(OPENWEATHER_PERIOD, lights_weather_indication)
    t.daemon = True
    t.start()

    openweather_states = get_file(OPENWEATHER_PATH)
    openweather_api = get_file(CRED_FILE_PATH)
    openweather_url = 'http://api.openweathermap.org/data/2.5/{0}&units=metric&appid={1}'.format(
        OPENWEATHER_URL, openweather_api['openweather'])

    r = requests.get(openweather_url).json()

    # build my dictionary array to write to database
    meas = {}
    meas['berlin_temperature'] = round(float(r['main']['temp']), 2)
    meas['berlin_humidity'] = round(float(r['main']['humidity']), 2)
    meas['weather_state'] = r['weather'][0]['description']
    meas['berlin_pressure'] = round(float(r['main']['pressure']), 2)
    meas['berlin_wind_speed_kph'] = round(float(r['wind']['speed']), 2)

    if str(r['weather'][0]['id']) in openweather_states:
        print(ts() + " - weather is {0} now {1}C and {2}%RH".format(meas['weather_state'],
            meas['berlin_temperature'], meas['berlin_humidity']))
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
    # override_default_values()
    lights_weather_indication()
    # lights_schedule()
    # lights_rule()

    while(True):
        time.sleep(0.5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.exception("keyboard interrupt")
        stop_application()
