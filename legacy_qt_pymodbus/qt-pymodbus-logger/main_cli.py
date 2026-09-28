import time, os
from config_manager import load_config
from storage.csv_logger import CSVLogger
from storage.mysql_logger import MySQLLogger
from modbus_worker import ModbusPoller

def main():
    cfg = load_config()
    modbus = cfg['Modbus']
    logger_cfg = cfg['Logger']

    loggers = []
    if logger_cfg.get('enable_csv','true').lower() in ('1','true','yes'):
        csv_path = logger_cfg.get('csv_file','logs/modbus_data.csv')
        loggers.append(CSVLogger(csv_path))
    if logger_cfg.get('enable_mysql','false').lower() in ('1','true','yes'):
        mysql_conf = cfg['MYSQL']
        mysql_conf = {k: mysql_conf.get(k) for k in ('host','user','password','database','table')}
        loggers.append(MySQLLogger(mysql_conf))

    poll = ModbusPoller(dict(modbus), logger_list=loggers)
    interval = float(modbus.get('poll_interval', 1.0))
    try:
        poll.run_loop(interval)
    except KeyboardInterrupt:
        print('Stopped by user')

if __name__ == '__main__':
    main()
