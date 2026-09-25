#!/usr/bin/env python3
import serial
import struct
import time

PORT = "/dev/ttyACM1"   # sesuai log Anda
BAUD = 9600
FRAME_LEN = 21          # << INI YANG BENAR

# -----------------------------
def hexdump(b):
    return " ".join(f"{x:02X}" for x in b)

def checksum_calc(frame):
    # checksum = sum of first 16 bytes, low byte
    return sum(frame[0:16]) & 0xFF

# -----------------------------
def decode_frame(f):
    d = {}

    # Wind direction (9 bit)
    wd_raw = ((f[4] & 0x01) << 8) | f[5]
    d["wind_dir_deg"] = None if wd_raw == 0x1FF else wd_raw

    # Temperature
    temp_raw = ((f[7] & 0x07) << 8) | f[8]
    d["temperature_C"] = (temp_raw - 400) / 10.0

    # Humidity
    d["humidity_pct"] = f[10]

    # Wind speed
    ws_raw = f[12]
    d["wind_speed_ms"] = (ws_raw / 8.0) * 1.12

    # Gust
    d["gust_ms"] = f[14] * 1.12

    # Rain (accumulated)
    rain_raw = struct.unpack(">H", f[16:18])[0]
    d["rain_mm"] = rain_raw * 0.3

    # UV
    d["uv_uW_cm2"] = f[18]

    # Light
    light_raw = struct.unpack(">H", f[19:21])[0]
    d["light_lux"] = light_raw / 10.0

    return d

# -----------------------------
def main():
    ser = serial.Serial(PORT, BAUD, timeout=1)
    buffer = bytearray()

    print(f"[INFO] Opened {PORT} @ {BAUD} 8N1")
    print("[INFO] Waiting for data...\n")

    while True:
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"[RX ] {hexdump(data)}")
            buffer.extend(data)

        while len(buffer) >= FRAME_LEN:
            # sync to 0x24
            if buffer[0] != 0x24:
                dropped = buffer.pop(0)
                print(f"[SYNC] Drop byte 0x{dropped:02X}")
                continue

            frame = buffer[:FRAME_LEN]
            buffer = buffer[FRAME_LEN:]

            print("\n[FRAME] ===============================")
            print("[HEX ]", hexdump(frame))

            chk_rx = frame[16]
            chk_calc = checksum_calc(frame)

            print(f"[CHK ] recv=0x{chk_rx:02X} calc=0x{chk_calc:02X} "
                  f"{'OK' if chk_rx == chk_calc else 'BAD'}")

            if chk_rx != chk_calc:
                print("[WARN] Checksum mismatch, frame ignored\n")
                continue

            decoded = decode_frame(frame)
            print("[DATA]")
            for k, v in decoded.items():
                print(f"  {k:16s}: {v}")

            print("[END ] ===============================\n")

        time.sleep(0.01)

# -----------------------------
if __name__ == "__main__":
    main()
