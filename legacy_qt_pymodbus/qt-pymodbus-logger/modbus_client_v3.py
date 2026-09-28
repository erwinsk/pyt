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

        # --- deteksi versi pymodbus ---
        from pymodbus import __version__
        parts = __version__.split('.')
        self.v_major = int(parts[0]) if parts and parts[0].isdigit() else 0
        self.v_minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        # true jika sudah >= 3.x
        self.v3 = self.v_major >= 3

    def open(self):
        if self.mode == 'rtu':
            self.client = ModbusSerialClient(
                method=self.cfg.get('method', 'rtu'),
                port=self.cfg.get('port', '/dev/ttyUSB0'),
                baudrate=int(self.cfg.get('baudrate', 9600)),
                bytesize=int(self.cfg.get('bytesize', 8)),
                parity=self.cfg.get('parity', 'N'),
                stopbits=int(self.cfg.get('stopbits', 1)),
                timeout=float(self.cfg.get('timeout', 1))
            )
        else:
            self.client = ModbusTcpClient(
                host=self.cfg.get('host', '127.0.0.1'),
                port=int(self.cfg.get('tcp_port', 502)),
                timeout=float(self.cfg.get('timeout', 1))
            )
        return self.client.connect()

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

    # --- internal helper agar lintas versi ---
    def _call(self, func, address, count=None, unit=1, values=None):
        """Handle argumen unit/slave/device_id per versi"""
        kwargs = {"address": address}

        if count is not None:
            kwargs["count"] = count
        if values is not None:
            kwargs["values" if isinstance(values, (list, tuple)) else "value"] = values

        # versi 3.11+ pakai device_id
        if self.v_major >= 3 and self.v_minor >= 11:
            kwargs["device_id"] = unit
        # versi 3.0–3.10 pakai slave
        elif self.v_major >= 3:
            kwargs["slave"] = unit
        # versi lama (<3)
        else:
            kwargs["unit"] = unit

        return func(**kwargs)

    # === wrappers ===
    def read_holding(self, address, count, unit=1):
        return self._call(self.client.read_holding_registers, address, count, unit)

    def read_input(self, address, count, unit=1):
        return self._call(self.client.read_input_registers, address, count, unit)

    def read_coils(self, address, count, unit=1):
        return self._call(self.client.read_coils, address, count, unit)

    def read_discrete(self, address, count, unit=1):
        return self._call(self.client.read_discrete_inputs, address, count, unit)

    def write_register(self, address, value, unit=1):
        return self._call(self.client.write_register, address, unit=unit, values=value)

    def write_registers(self, address, values, unit=1):
        return self._call(self.client.write_registers, address, unit=unit, values=values)

    # === decode helpers ===
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
    def decode_u16(reg):
        return reg & 0xFFFF