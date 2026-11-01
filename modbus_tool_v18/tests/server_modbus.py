"""Server Modbus TCP mini untuk pengujian (tanpa bergantung pada API server pymodbus
yang berubah antar versi). Mendukung FC 01-06, 15, 16, 22. Slave ID yang tidak
terdaftar TIDAK dijawab sama sekali (meniru perangkat tak ada -> timeout di client)."""
import socket
import socketserver
import struct
import threading
import time


class ServerModbusUji:
    def __init__(self, daftar_id=(1,), jumlah_register=300):
        self.n = jumlah_register
        self.data = {uid: {'hr': [0] * jumlah_register, 'ir': [0] * jumlah_register,
                           'co': [False] * jumlah_register, 'di': [False] * jumlah_register}
                     for uid in daftar_id}
        self.jumlah_request = 0
        self.log_fc = []
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self._server = None
        self._thread = None

    # ---- akses data dari test
    def isi_holding(self, uid, alamat, nilai):
        self.data[uid]['hr'][alamat:alamat + len(nilai)] = list(nilai)

    def baca_holding(self, uid, alamat, jumlah):
        return list(self.data[uid]['hr'][alamat:alamat + jumlah])

    def baca_coil(self, uid, alamat, jumlah):
        return list(self.data[uid]['co'][alamat:alamat + jumlah])

    # ---- protokol
    def _proses(self, uid, pdu):
        d = self.data[uid]
        fc = pdu[0]
        self.log_fc.append(fc)

        def salah(kode):
            return bytes([fc | 0x80, kode])

        try:
            if fc in (1, 2):
                alamat, jumlah = struct.unpack(">HH", pdu[1:5])
                tabel = d['co'] if fc == 1 else d['di']
                if alamat + jumlah > self.n:
                    return salah(2)
                bit = tabel[alamat:alamat + jumlah]
                byte = bytearray((jumlah + 7) // 8)
                for i, b in enumerate(bit):
                    if b:
                        byte[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(byte)]) + bytes(byte)
            if fc in (3, 4):
                alamat, jumlah = struct.unpack(">HH", pdu[1:5])
                tabel = d['hr'] if fc == 3 else d['ir']
                if alamat + jumlah > self.n:
                    return salah(2)
                return bytes([fc, jumlah * 2]) + struct.pack(f">{jumlah}H", *tabel[alamat:alamat + jumlah])
            if fc == 5:
                alamat, nilai = struct.unpack(">HH", pdu[1:5])
                if alamat >= self.n:
                    return salah(2)
                d['co'][alamat] = (nilai == 0xFF00)
                return pdu[:5]
            if fc == 6:
                alamat, nilai = struct.unpack(">HH", pdu[1:5])
                if alamat >= self.n:
                    return salah(2)
                d['hr'][alamat] = nilai
                return pdu[:5]
            if fc == 15:
                alamat, jumlah, banyak_byte = struct.unpack(">HHB", pdu[1:6])
                if alamat + jumlah > self.n:
                    return salah(2)
                for i in range(jumlah):
                    d['co'][alamat + i] = bool(pdu[6 + i // 8] >> (i % 8) & 1)
                return pdu[:5]
            if fc == 16:
                alamat, jumlah, banyak_byte = struct.unpack(">HHB", pdu[1:6])
                if alamat + jumlah > self.n:
                    return salah(2)
                d['hr'][alamat:alamat + jumlah] = list(struct.unpack(f">{jumlah}H", pdu[6:6 + jumlah * 2]))
                return pdu[:5]
            if fc == 22:
                alamat, and_m, or_m = struct.unpack(">HHH", pdu[1:7])
                if alamat >= self.n:
                    return salah(2)
                lama = d['hr'][alamat]
                d['hr'][alamat] = (lama & and_m) | (or_m & (~and_m & 0xFFFF))
                return pdu[:7]
            return salah(1)
        except Exception:
            return salah(3)

    def start(self):
        server_uji = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                sock = self.request
                sock.settimeout(30)
                while True:
                    try:
                        header = self._baca(sock, 7)
                        if header is None:
                            return
                        tid, pid, panjang, uid = struct.unpack(">HHHB", header)
                        pdu = self._baca(sock, panjang - 1)
                        if pdu is None:
                            return
                        server_uji.jumlah_request += 1
                        if uid not in server_uji.data:
                            continue          # perangkat tidak ada -> tidak menjawab
                        jawab = server_uji._proses(uid, pdu)
                        sock.sendall(struct.pack(">HHHB", tid, pid, len(jawab) + 1, uid) + jawab)
                    except (OSError, socket.timeout):
                        return

            @staticmethod
            def _baca(sock, n):
                buf = b""
                while len(buf) < n:
                    potong = sock.recv(n - len(buf))
                    if not potong:
                        return None
                    buf += potong
                return buf

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
