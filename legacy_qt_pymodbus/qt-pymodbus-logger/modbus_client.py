import struct
try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except Exception:
    try:
        from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient
    except Exception:
        raise ImportError('pymodbus client not found; install pymodbus')

class ModbusClient:
    def __init__(self, mode='rtu', cfg=None):
        self.mode = mode.lower()
        self.cfg = cfg or {}
        self.client = None

    def open(self):
        if self.mode == 'rtu':
            self.client = ModbusSerialClient(
                method=self.cfg.get('method','rtu'),
                port=self.cfg.get('port','/dev/ttyUSB0'),
                baudrate=int(self.cfg.get('baudrate',9600)),
                bytesize=int(self.cfg.get('bytesize',8)),
                parity=self.cfg.get('parity','N'),
                stopbits=int(self.cfg.get('stopbits',1)),
                timeout=float(self.cfg.get('timeout',1))
            )
        else:
            self.client = ModbusTcpClient(
                host=self.cfg.get('host','127.0.0.1'),
                port=int(self.cfg.get('tcp_port',502)),
                timeout=float(self.cfg.get('timeout',1))
            )
        return self.client.connect()

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

    # wrappers
    def read_holding(self, address, count, unit=1):
        return self.client.read_holding_registers(address=address, count=count, unit=unit)

    def read_input(self, address, count, unit=1):
        return self.client.read_input_registers(address=address, count=count, unit=unit)

    def read_coils(self, address, count, unit=1):
        return self.client.read_coils(address=address, count=count, unit=unit)

    def read_discrete(self, address, count, unit=1):
        return self.client.read_discrete_inputs(address=address, count=count, unit=unit)

    # decode helpers (4 float32 encodings + u16)
    @staticmethod
    def decode_float32_from_regs(reg_high, reg_low, encoding='ABCD'):
        A = (reg_high >> 8) & 0xFF
        B = reg_high & 0xFF
        C = (reg_low >> 8) & 0xFF
        D = reg_low & 0xFF
        enc = encoding.upper()
        import struct
        if enc == 'ABCD':
            raw = bytes([A,B,C,D]); val = struct.unpack('>f', raw)[0]
        elif enc == 'CDAB':
            raw = bytes([C,D,A,B]); val = struct.unpack('>f', raw)[0]
        elif enc == 'BADC':
            raw = bytes([B,A,D,C]); val = struct.unpack('>f', raw)[0]
        elif enc == 'DCBA':
            raw = bytes([D,C,B,A]); val = struct.unpack('>f', raw)[0]
        else:
            raise ValueError('Unsupported encoding')
        return val

    @staticmethod
    def decode_u16(reg):
        return reg & 0xFFFF
