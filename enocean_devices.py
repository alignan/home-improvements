#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import time
import datetime
from enocean.consolelogger import init_logging
import enocean.utils
from enocean.communicators.serialcommunicator import SerialCommunicator
from enocean.protocol.packet import RadioPacket
from enocean.protocol.constants import PACKET, RORG
import traceback
from influxdb import InfluxDBClient

DDDBB_NAME     = "local"
DDBB_ADDRESS   = "localhost"
DDBB_PORT      = 8086

ENOCEAN_DEVICES = {
    '01:80:F5:BC': 'main bedroom'
}

influxClient = None

try:
    import queue
except ImportError:
    import Queue as queue

# returns timestamp as string
def ts():
    return str(datetime.datetime.now())

# connects to the influxDB database:
def connect_to_ddbb():
    global influxClient
    while True:
        try:
            time.sleep(5)
            influxClient = InfluxDBClient(DDBB_ADDRESS, DDBB_PORT, "root", "root")
            influxClient.create_database(DDBB_NAME)
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
            'measurement':key,
            'fields': {'value': val }
            })
        influxClient.write_points(data, database=DDBB_NAME, time_precision='ms')
        data = []

def main():
    global influxClient

    init_logging()
    communicator = SerialCommunicator(port='/dev/ttyUSB0')
    communicator.start()

    print('The Base ID of your module is %s.' % enocean.utils.to_hex_string(communicator.base_id))

    # connect to the database
    # connect_to_ddbb()

    # endless loop receiving radio packets
    while communicator.is_alive():
        try:
            # Loop to empty the queue...
            packet = communicator.receive.get(block=True, timeout=1)

            # RORG: 0xA5, FUNC: 0x02, TYPE: 0x05, Manufacturer: 0x2D
            # 01:80:F5:BC->FF:FF:FF:FF (-74 dBm): 0x01 ['0xa5', '0x8', '0x28', '0x2d', '0x80', '0x1',

            if packet.packet_type == PACKET.RADIO:
                if packet.rorg == RORG.BS4:
                    packet.select_eep(0x02, 0x05)
                    packet.parse_eep()

                    if packet.sender_hex in ENOCEAN_DEVICES:
                        print(packet.sender_hex)
                        for k in packet.parsed:
                            print('%s: %s' % (k, packet.parsed[k]))
        except queue.Empty:
            continue
        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc(file=sys.stdout)
            break

    # if we reached here, exit
    stop_application()

# in case of termination signal exit
def stop_application():
    if communicator.is_alive():
        communicator.stop()
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_application()
