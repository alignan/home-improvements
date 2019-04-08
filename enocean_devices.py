#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import sys
import yaml
import time
import datetime
import logging
import logging.config
# from enocean.consolelogger import init_logging
import enocean.utils
from enocean.communicators.serialcommunicator import SerialCommunicator
from enocean.protocol.packet import RadioPacket
from enocean.protocol.constants import PACKET, RORG
import traceback
from influxdb import InfluxDBClient

DDBB_NAME      = "local"
DDBB_ADDRESS   = "localhost"
DDBB_PORT      = 8086

# TODO: expand the 'meas' type as list as sensors may have > 1 attribute
ENOCEAN_DEVICES = {
    '01:80:F5:BC': {
        'name': 'main_bedroom_temperature',
        'func': 0x02,
        'type': 0x05,
        'meas': 'TMP'
    },
    '01:9C:44:11': {
        'name': 'living_room_CO2',
        'func': 0x09,
        'type': 0x09,
        'meas': 'CO2'
    },
    '05:10:19:64': {
        'name': 'balcony_temperature',
        'func': 0x02,
        'type': 0x13,
        'meas': 'TMP'
    },
    '01:93:BA:EF': {
        'name': 'bathroom_presence',
        'func': 0x07,
        'type': 0x01,
        'meas': 'PIR'
    }
}

influxClient = None
communicator = None

LOGGING_PATH = 'enocean_log_config.yaml'

with open(os.path.join(os.path.dirname(__file__), LOGGING_PATH)) as f:
    config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)
logger = logging.getLogger(__name__)

try:
    import queue
except ImportError:
    import Queue as queue

# returns timestamp as string
def ts():
    return str(datetime.datetime.now())

# connects to the influxDB database
def connect_to_ddbb():
    global influxClient
    while True:
        try:
            time.sleep(1)
            influxClient = InfluxDBClient(DDBB_ADDRESS, DDBB_PORT, "root",
                "root")
            influxClient.create_database(DDBB_NAME)
            break
        except Exception as e:
            logger.exception(e)

# publish to the influxDB database
def publish_to_database(values):
    global influxClient

    data = []
    # takes an array of dictionaries and builds a list
    for key, val in values.iteritems():
        data.append({
            'measurement':key,
            'fields': {'value': val }
            })
        influxClient.write_points(data, database=DDBB_NAME,
            time_precision='ms')
        data = []

# parses and publishes sensor data to the database
def enocean_parse_and_publish(data, dev):
    meas = {}
    data.select_eep(dev['func'], dev['type'])
    data.parse_eep()
    if dev['meas'] in data.parsed:
        if isinstance(data.parsed[dev['meas']]['value'], (int, long)):
            meas[dev['name']] = round(data.parsed[dev['meas']]['value'], 2)
        else:
            meas[dev['name']] = data.parsed[dev['meas']]['value']
            if 'on' in meas[dev['name']]:
                meas[dev['name']] = 'occupied'
            if 'off' in meas[dev['name']]:
                meas[dev['name']] = 'empty'
        logger.info("PUB --> {}: {}".format(dev['name'], meas[dev['name']]))
        return meas

def main():
    global influxClient, communicator

    # init_logging()
    communicator = SerialCommunicator(port='/dev/ttyUSB0')
    communicator.start()

    logger.info('The Base ID of your module is %s.' % 
        enocean.utils.to_hex_string(communicator.base_id))

    # connect to the database
    connect_to_ddbb()

    # endless loop receiving radio packets
    while communicator.is_alive():
        try:
            # Loop to empty the queue...
            packet = communicator.receive.get(block=True, timeout=1)

            # RORG: 0xA5, FUNC: 0x02, TYPE: 0x05, Manufacturer: 0x2D
            # 01:80:F5:BC->FF:FF:FF:FF (-74 dBm): 0x01 ['0xa5', '0x8', '0x28', '0x2d', '0x80', '0x1',

            if packet.packet_type == PACKET.RADIO:
                if packet.rorg == RORG.BS4 and packet.sender_hex in ENOCEAN_DEVICES:
                    meas = enocean_parse_and_publish(packet,
                        ENOCEAN_DEVICES[packet.sender_hex])
                    if meas is not None:
                        publish_to_database(meas)

        except queue.Empty:
            continue
        except KeyboardInterrupt:
            logger.exception("Manually closing the application, exit")
            break
        except Exception as exc:
            logger.exception(exc)
            break

        time.sleep(0.1)

    # if we reached here, exit
    stop_application()

# in case of termination signal exit
def stop_application():
    global communicator
    if communicator.is_alive():
        communicator.stop()
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_application()
