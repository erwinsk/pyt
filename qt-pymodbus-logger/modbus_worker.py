from datetime import datetime
import time
from modbus_client_v3 import ModbusClient

class ModbusPoller:
    def __init__(self, cfg, logger_list=None):
        self.cfg = cfg
        self.logger_list = logger_list or []

    def run_once(self):
        mc = ModbusClient(mode=self.cfg.get('type', 'rtu'), cfg=self.cfg)
        ok = mc.open()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        results = []
        if not ok:
            raise ConnectionError('Cannot open modbus client')

        try:
            func = self.cfg.get('function', 'holding').lower()
            addr = int(self.cfg.get('register', 0))
            qty = int(self.cfg.get('quantity', 2))
            uid = int(self.cfg.get('unit_id', 1))

            # baca sesuai function
            if func in ('holding', 'read_holding_registers', 'read_holding'):
                rr = mc.read_holding(addr, qty, unit=uid)
                regs = getattr(rr, 'registers', [])
            elif func in ('input', 'read_input_registers', 'input_register'):
                rr = mc.read_input(addr, qty, unit=uid)
                regs = getattr(rr, 'registers', [])
            elif func in ('coils', 'read_coils'):
                rr = mc.read_coils(addr, qty, unit=uid)
                regs = getattr(rr, 'bits', [])
            elif func in ('discrete', 'discrete_input', 'read_discrete_inputs'):
                rr = mc.read_discrete(addr, qty, unit=uid)
                regs = getattr(rr, 'bits', [])
            else:
                regs = []

            encoding = self.cfg.get('encoding', 'float32be').lower()
            entries = []

            if isinstance(regs, list) and len(regs) > 0:
                if encoding.startswith('float32'):
                    for i in range(0, len(regs), 2):
                        try:
                            if encoding == 'float32be':
                                v = ModbusClient.decode_float32_from_regs(regs[i], regs[i+1], encoding='ABCD')
                            elif encoding == 'float32le':
                                v = ModbusClient.decode_float32_from_regs(regs[i], regs[i+1], encoding='DCBA')
                            elif encoding == 'float32cdab':
                                v = ModbusClient.decode_float32_from_regs(regs[i], regs[i+1], encoding='CDAB')
                            elif encoding == 'float32badc':
                                v = ModbusClient.decode_float32_from_regs(regs[i], regs[i+1], encoding='BADC')
                            else:
                                v = None
                        except Exception:
                            v = None
                        entries.append({'value': v})

                elif encoding == 'u16':
                    for r in regs:
                        try:
                            v = ModbusClient.decode_u16(r)
                        except Exception:
                            v = None
                        entries.append({'value': v})

            # kirim ke semua logger
            for logger in self.logger_list:
                try:
                    logger.log(timestamp, entries)
                except Exception:
                    pass

            results = entries
        finally:
            mc.close()

        return timestamp, results

    def run_loop(self, interval_s=1.0):
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                break
            except Exception:
                pass
            time.sleep(interval_s)