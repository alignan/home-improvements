#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import time
import datetime
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

ENOCEAN_DEVICES = {
    '01:80:F5:BC': 'main_bedroom_temperature',
    '01:9C:44:11': 'living_room_CO2'
}

influxClient = None
communicator = None

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
            influxClient = InfluxDBClient(DDBB_ADDRESS, DDBB_PORT, "root", "root")
            influxClient.create_database(DDBB_NAME)
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
            'measurement':key,
            'fields': {'value': val }
            })
        influxClient.write_points(data, database=DDBB_NAME, time_precision='ms')
        data = []

def main():
    global influxClient, communicator

    # init_logging()
    communicator = SerialCommunicator(port='/dev/ttyUSB0')
    communicator.start()

    print('The Base ID of your module is %s.' % enocean.utils.to_hex_string(communicator.base_id))

    # connect to the database
    connect_to_ddbb()

    # endless loop receiving radio packets
    while communicator.is_alive():
        try:
            # Loop to empty the queue...
            packet = communicator.receive.get(block=True, timeout=1)

            # RORG: 0xA5, FUNC: 0x02, TYPE: 0x05, Manufacturer: 0x2D
            # 01:80:F5:BC->FF:FF:FF:FF (-74 dBm): 0x01 ['0xa5', '0x8', '0x28', '0x2d', '0x80', '0x1',

            meas = {}

            if packet.packet_type == PACKET.RADIO:
                if packet.rorg == RORG.BS4 and packet.sender_hex in ENOCEAN_DEVICES:

                    # a hack as the rorg_type and rorg_func fields are only populated when the learn bit is set,
                    # perhaps something I don't understand about the protocol... I'm taking the lazy approach...
                    if ENOCEAN_DEVICES[packet.sender_hex] == 'main_bedroom_temperature':
                    # if packet.rorg_type == 0x05 and packet.rorg_func == 0x02:
                        packet.select_eep(0x02, 0x05)
                        packet.parse_eep()
                        meas[ENOCEAN_DEVICES[packet.sender_hex]] = round(packet.parsed['TMP']['value'], 2)
                    if ENOCEAN_DEVICES[packet.sender_hex] == 'living_room_CO2':
                    # if packet.rorg_type == 0x09 and packet.rorg_func == 0x09:
                        packet.select_eep(0x09, 0x09)
                        packet.parse_eep()
                        meas[ENOCEAN_DEVICES[packet.sender_hex]] = round(packet.parsed['CO2']['value'], 2)
            if meas:
                publish_to_database(meas)

        except queue.Empty:
            continue
        except KeyboardInterrupt:
            print(ts() + " - Manually closing the application, exit")
            break
        except Exception as exc:
            print(str(exc))
            traceback.print_exc(file=sys.stdout)
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
