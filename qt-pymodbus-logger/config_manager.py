import os, configparser
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.ini")

def load_config(path=None):
    p = path or CONFIG_FILE
    config = configparser.ConfigParser()
    if not os.path.exists(p):
        # create default minimal config
        config['Modbus'] = {
            'type': 'rtu',
            'port': '/dev/ttyUSB0',
            'baudrate': '9600',
            'bytesize': '8',
            'parity': 'N',
            'stopbits': '1',
            'timeout': '1',
            'host': '127.0.0.1',
            'tcp_port': '502',
            'unit_id': '1',
            'register': '0',
            'quantity': '2',
            'encoding': 'float32be',
            'poll_interval': '1.0',
        }
        config['Logger'] = {
            'enable_csv': 'true',
            'csv_file': 'logs/modbus_data.csv',
            'enable_mysql': 'false',
        }
        config['MYSQL'] = {
            'host': 'localhost',
            'user': 'root',
            'password': '',
            'database': 'modbus',
            'table': 'sensor_data',
        }
        config['UI'] = {'enable_graph': 'false'}
        with open(p, 'w') as f:
            config.write(f)
    else:
        config.read(p)
    return config

def save_config(config, path=None):
    p = path or CONFIG_FILE
    with open(p, 'w') as f:
        config.write(f)
