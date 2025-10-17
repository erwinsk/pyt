import struct
import logging

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except Exception:
    try:
        from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient
    except Exception:
        raise ImportError('pymodbus client not found; install pymodbus')


class ModbusFrameHandler(logging.Handler):
    def __init__(self, client):
        super().__init__()
        self.client = client

    def emit(self, record):
        msg = record.getMessage()
        if not record.name.startswith("pymodbus.transaction"):
            return

        if "SEND:" in msg or "RECV:" in msg:
            try:
                parts = msg.split(":", 1)
                if len(parts) < 2:
                    return
                data_part = parts[1]

                hex_tokens = []
                for token in data_part.strip().split():
                    token = token.strip().lower()
                    if token.startswith("0x"):
                        token = token[2:]
                    if all(c in "0123456789abcdef" for c in token) and token:
                        if len(token) == 1:   # <<=== FIX di sini
                            token = "0" + token
                        hex_tokens.append(token)

                if not hex_tokens:
                    return

                hex_str = "".join(hex_tokens)
                data_bytes = bytes.fromhex(hex_str)

                if "SEND:" in msg:
                    self.client.last_tx = data_bytes
                elif "RECV:" in msg:
                    self.client.last_rx = data_bytes

            except Exception as e:
                print(f"[WARN] Parsing Modbus log failed: {e}")

class ModbusClient:
    def __init__(self, mode='rtu', cfg=None):
        self.mode = mode.lower()
        self.cfg = cfg or {}
        self.client = None
        self.last_tx = None
        self.last_rx = None
        self.handler = ModbusFrameHandler(self)
        logger = logging.getLogger("pymodbus.transaction")
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)

        # Deteksi versi utama
        from pymodbus import __version__
        self.v3 = int(__version__.split('.')[0]) >= 3

    def open(self):
        if self.mode == 'rtu':
            self.client = ModbusSerialClient(
                method='rtu',
                port=self.cfg.get('port', '/dev/ttyUSB0'),
                baudrate=self.cfg.get('baudrate', 9600),
                parity=self.cfg.get('parity', 'N'),
                bytesize=self.cfg.get('bytesize', 8),
                stopbits=self.cfg.get('stopbits', 1),
                timeout=self.cfg.get('timeout', 1.0)
            )
        else:
            self.client = ModbusTcpClient(
                host=self.cfg.get('host', '127.0.0.1'),
                port=self.cfg.get('port', 502),
                timeout=self.cfg.get('timeout', 1.0)
            )
        return self.client.connect()

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    # === helper internal ===
    def _read(self, func, address, count, unit):
        if self.v3:
            # Pymodbus 3.x: wajib pakai keyword
            return func(address=address, count=count, device_id=unit)
        else:
            # Pymodbus 2.x: masih pakai unit
            return func(address, count, unit=unit)

    def _write(self, func, address, values, unit):
        if self.v3:
            if isinstance(values, (list, tuple)):
                return func(address=address, values=values, device_id=unit)
            else:
                return func(address=address, value=values, device_id=unit)
        else:
            if isinstance(values, (list, tuple)):
                return func(address, values, unit=unit)
            else:
                return func(address, values, unit=unit)

    # === API user ===
    def read_holding(self, address, count, unit=1):
        return self._read(self.client.read_holding_registers, address, count, unit)

    def read_input(self, address, count, unit=1):
        return self._read(self.client.read_input_registers, address, count, unit)

    def read_coils(self, address, count, unit=1):
        return self._read(self.client.read_coils, address, count, unit)

    def read_discrete(self, address, count, unit=1):
        return self._read(self.client.read_discrete_inputs, address, count, unit)

    def write_register(self, address, value, unit=1):
        return self._write(self.client.write_register, address, value, unit)

    def write_registers(self, address, values, unit=1):
        return self._write(self.client.write_registers, address, values, unit)

    # === utilitas decoding ===
    @staticmethod
    def decode_float32_from_regs(reg_high, reg_low, encoding='ABCD'):
        A = (reg_high >> 8) & 0xFF
        B = reg_high & 0xFF
        C = (reg_low >> 8) & 0xFF
        D = reg_low & 0xFF
        enc = encoding.upper()
        if enc == 'ABCD':
            raw = bytes([A, B, C, D]); val = struct.unpack('>f', raw)[0]
        elif enc == 'CDAB':
            raw = bytes([C, D, A, B]); val = struct.unpack('>f', raw)[0]
        elif enc == 'BADC':
            raw = bytes([B, A, D, C]); val = struct.unpack('>f', raw)[0]
        elif enc == 'DCBA':
            raw = bytes([D, C, B, A]); val = struct.unpack('>f', raw)[0]
        else:
            raise ValueError('Unsupported encoding')
        return val

    @staticmethod
    def decode_u16(r):
        return r or 0