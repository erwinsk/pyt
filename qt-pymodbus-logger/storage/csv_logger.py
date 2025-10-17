import csv, os
from .base_logger import BaseLogger

class CSVLogger(BaseLogger):
    def __init__(self, path):
        self.path = path
        self._ensure_dir()

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def create_table_if_not_exists(self):
        # noop for CSV
        return

    def log_old(self, timestamp, data_list):
        # data_list: list of dicts {'sensor_code','sensor_name','value','encoding'}
        header = ['timestamp','sensor_code','sensor_name','value','encoding','quality','note']
        write_header = not os.path.exists(self.path) or os.path.getsize(self.path)==0
        with open(self.path, 'a', newline='') as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(header)
            for d in data_list:
                row = [
                    timestamp,
                    d.get('sensor_code',''),
                    d.get('sensor_name',''),
                    d.get('value', ''),
                    d.get('encoding',''),
                    d.get('quality','OK'),
                    d.get('note','')
                ]
                w.writerow(row)

    def log(self, timestamp, data_list):
        """
        Menyimpan data ke CSV dalam format sederhana:
        timestamp, value1, value2, value3, ...
        """
        if not data_list:
            return

        # Path file CSV
        filepath = self.path

        # Ambil semua nilai sensor
        values = [f"{d.get('value', ''):.6g}" if isinstance(d.get('value', 0), (int, float)) else str(d.get('value', ''))
                for d in data_list]

        # Jika file kosong / belum ada → tulis header
        write_header = not os.path.exists(filepath) or os.path.getsize(filepath) == 0

        with open(filepath, 'a', newline='') as f:
            w = csv.writer(f)
            if write_header:
                headers = ["timestamp"] + [f"ch{i+1}" for i in range(len(values))]
                w.writerow(headers)

            # Tulis baris data
            w.writerow([timestamp] + values)