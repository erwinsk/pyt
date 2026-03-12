import sys
import socket
import ipaddress
from PyQt5.QtCore import Qt, QRunnable, QThreadPool, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QProgressBar, QMessageBox
)

# ---------- Worker signals ----------
class WorkerSignals(QObject):
    result = pyqtSignal(str, int, bool)  # host, port, is_open
    finished = pyqtSignal()

# ---------- Worker: scan single host:port ----------
class PortCheckWorker(QRunnable):
    def __init__(self, host: str, port: int, timeout: float = 0.5):
        super().__init__()
        self.host = host
        self.port = port
        self.timeout = timeout
        self.signals = WorkerSignals()

    def run(self):
        is_open = False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                code = sock.connect_ex((self.host, self.port))
                is_open = (code == 0)
        except Exception:
            is_open = False
        self.signals.result.emit(self.host, self.port, is_open)
        self.signals.finished.emit()


# ---------- Utilities ----------
def detect_local_ip():
    """
    Determine the local outbound IP by opening UDP socket to known remote.
    Doesn't send data on network.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # doesn't need to be reachable; OS chooses outbound interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # fallback
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def parse_hosts(input_text: str):
    """
    Accepts:
    - CIDR: 192.168.1.0/24
    - single IP: 192.168.1.10
    - range using dash between last octet: 192.168.1.10-20 (interpreted within same /24)
    - comma separated mix
    Returns list of IP strings
    """
    hosts = []
    parts = [p.strip() for p in input_text.split(",") if p.strip()]
    for p in parts:
        if "/" in p:
            try:
                net = ipaddress.ip_network(p, strict=False)
                for ip in net.hosts():
                    hosts.append(str(ip))
            except Exception:
                continue
        elif "-" in p:
            # try full range or last-octet shorthand
            try:
                a, b = p.split("-")
                a = a.strip(); b = b.strip()
                # if a and b are full IPs
                if "." in b:
                    start_ip = ipaddress.IPv4Address(a)
                    end_ip = ipaddress.IPv4Address(b)
                else:
                    # interpret b as last octet within same /24 as a
                    base = ".".join(a.split(".")[:3])
                    start_ip = ipaddress.IPv4Address(a)
                    end_ip = ipaddress.IPv4Address(f"{base}.{b}")
                # iterate inclusive
                cur = int(start_ip)
                end = int(end_ip)
                for val in range(cur, end + 1):
                    hosts.append(str(ipaddress.IPv4Address(val)))
            except Exception:
                continue
        else:
            # single IP
            try:
                ip = ipaddress.ip_address(p)
                hosts.append(str(ip))
            except Exception:
                continue
    # remove duplicates, keep order
    seen = set()
    out = []
    for h in hosts:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out

def parse_ports(input_text: str):
    """
    Accepts comma separated ports and ranges, e.g.:
    "22,80,8000-8010"
    Returns sorted list of ints
    """
    ports = set()
    parts = [p.strip() for p in input_text.split(",") if p.strip()]
    for p in parts:
        if "-" in p:
            try:
                a, b = p.split("-")
                start = int(a); end = int(b)
                if start > end:
                    start, end = end, start
                for port in range(start, end+1):
                    if 1 <= port <= 65535:
                        ports.add(port)
            except Exception:
                continue
        else:
            try:
                port = int(p)
                if 1 <= port <= 65535:
                    ports.add(port)
            except Exception:
                continue
    return sorted(ports)


# ---------- Main GUI ----------
class SubnetPortScanner(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Subnet + Port Scanner")
        self.resize(700, 500)

        self.threadpool = QThreadPool.globalInstance()
        self.active_jobs = 0
        self.should_stop = False

        layout = QVBoxLayout(self)

        # Auto-detect info
        ip = detect_local_ip()
        self.auto_hint = QLabel(f"Detected local IP: {ip} (default /24 if you use 'auto')")

        layout.addWidget(self.auto_hint)

        # Hosts input
        h_host = QHBoxLayout()
        h_host.addWidget(QLabel("Targets (CIDR, IP, range, or 'auto')"))
        self.host_input = QLineEdit("auto")  # default auto
        h_host.addWidget(self.host_input)
        layout.addLayout(h_host)

        # Ports input
        h_port = QHBoxLayout()
        h_port.addWidget(QLabel("Ports (comma/ranges):"))
        self.port_input = QLineEdit("22,502")  # default example
        h_port.addWidget(self.port_input)
        layout.addLayout(h_port)

        # Timeout and controls
        h_ctrl = QHBoxLayout()
        h_ctrl.addWidget(QLabel("Timeout (s):"))
        self.timeout_input = QLineEdit("0.3")
        self.timeout_input.setMaximumWidth(80)
        h_ctrl.addWidget(self.timeout_input)

        self.start_btn = QPushButton("Start Scan")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        h_ctrl.addWidget(self.start_btn)
        h_ctrl.addWidget(self.stop_btn)
        layout.addLayout(h_ctrl)

        # Progress + results
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        self.result_list = QListWidget()
        layout.addWidget(self.result_list)

        # Connections
        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.request_stop)

    def request_stop(self):
        self.should_stop = True
        self.stop_btn.setEnabled(False)

    def expand_targets_from_input(self, text: str):
        text = text.strip()
        if not text or text.lower() == "auto":
            # auto-detect local ip and assume /24
            local = detect_local_ip()
            base = ".".join(local.split(".")[:3]) + ".0/24"
            return parse_hosts(base)
        else:
            return parse_hosts(text)

    def start_scan(self):
        # parse timeout
        try:
            timeout = float(self.timeout_input.text())
            if timeout <= 0:
                raise ValueError
        except Exception:
            QMessageBox.warning(self, "Timeout salah", "Masukkan timeout positif (mis. 0.3).")
            return

        # parse targets
        raw_targets = self.host_input.text().strip()
        targets = self.expand_targets_from_input(raw_targets)
        if not targets:
            QMessageBox.warning(self, "Targets kosong", "Tidak ada target valid. Gunakan 'auto' atau masukkan CIDR/IP/range.")
            return

        # parse ports
        ports = parse_ports(self.port_input.text())
        if not ports:
            QMessageBox.warning(self, "Ports kosong", "Masukkan setidaknya 1 port (mis. 22,502 atau 20-25).")
            return

        # prepare UI
        self.result_list.clear()
        total = len(targets) * len(ports)
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.active_jobs = 0
        self.should_stop = False

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # submit jobs
        for host in targets:
            if self.should_stop:
                break
            for port in ports:
                if self.should_stop:
                    break
                worker = PortCheckWorker(host, port, timeout=timeout)
                worker.signals.result.connect(self.handle_result)
                worker.signals.finished.connect(self._job_finished_signal)
                self.active_jobs += 1
                self.threadpool.start(worker)

        if self.active_jobs == 0:
            self.scan_finished()

    def _job_finished_signal(self):
        # update progress and active_jobs
        cur = self.progress.value() + 1
        self.progress.setValue(cur)
        self.active_jobs -= 1
        if self.active_jobs <= 0 or self.should_stop:
            self.scan_finished()

    def handle_result(self, host: str, port: int, is_open: bool):
        if is_open:
            self.result_list.addItem(f"{host}:{port} — OPEN")
        # optional: show closed ports uncomment next line
        # else:
        #     self.result_list.addItem(f"{host}:{port} — closed")

    def scan_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.should_stop:
            self.result_list.addItem("(Scan dihentikan oleh pengguna)")
        else:
            self.result_list.addItem("(Scan selesai)")
        self.active_jobs = 0
        self.should_stop = False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = SubnetPortScanner()
    w.show()
    sys.exit(app.exec_())