import pymysql
from .base_logger import BaseLogger

class MySQLLogger(BaseLogger):
    def __init__(self, cfg):
        self.cfg = cfg
        self.table = cfg.get('table', 'sensor_data')
        self.max_channels = 0
        try:
            self.create_table_if_not_exists()
        except Exception as e:
            print(f"MySQL table init failed: {e}")

    def connect(self):
        return pymysql.connect(
            host=self.cfg.get('host', 'localhost'),
            user=self.cfg.get('user', 'root'),
            password=self.cfg.get('password', ''),
            database=self.cfg.get('database', 'modbus'),
            autocommit=True
        )

    # --- Table creation ---
    def create_table_if_not_exists(self):
        """
        Membuat tabel dasar dengan timestamp dan minimal 1 kolom sensor.
        Kolom akan bertambah otomatis bila sensor > jumlah kolom.
        """
        conn = self.connect()
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS `{self.table}` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                ch1 DOUBLE
            ) ENGINE=InnoDB;
        """)
        conn.commit()
        conn.close()
        self.max_channels = self.get_current_channel_count()

    # --- Channel checker ---
    def get_current_channel_count(self):
        conn = self.connect()
        cur = conn.cursor()
        cur.execute(f"SHOW COLUMNS FROM `{self.table}` LIKE 'ch%';")
        cols = cur.fetchall()
        conn.close()
        return len(cols)

    def ensure_columns(self, required_count):
        """
        Pastikan jumlah kolom cukup untuk menampung semua channel.
        Tambah kolom baru bila perlu.
        """
        if required_count <= self.max_channels:
            return

        conn = self.connect()
        cur = conn.cursor()
        for i in range(self.max_channels + 1, required_count + 1):
            alter_sql = f"ALTER TABLE `{self.table}` ADD COLUMN ch{i} DOUBLE;"
            print(f"[MySQLLogger] Adding column ch{i}")
            cur.execute(alter_sql)
        conn.commit()
        conn.close()
        self.max_channels = required_count

    # --- Data insert ---
    def log(self, timestamp, data_list):
        """
        data_list: [{'value': 12.3}, {'value': 45.6}, ...] atau [12.3, 45.6, ...]
        """
        if not data_list:
            return

        # ambil nilai float saja
        if isinstance(data_list[0], dict):
            values = [d.get('value', None) for d in data_list]
        else:
            values = list(data_list)

        num_channels = len(values)
        # pastikan jumlah kolom cukup
        self.ensure_columns(num_channels)

        cols = ", ".join([f"ch{i+1}" for i in range(num_channels)])
        placeholders = ", ".join(["%s"] * (num_channels + 1))  # +1 untuk timestamp
        sql = f"INSERT INTO `{self.table}` (timestamp, {cols}) VALUES ({placeholders})"

        try:
            conn = self.connect()
            cur = conn.cursor()
            cur.execute(sql, [timestamp] + values)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"MySQL log error: {e}")