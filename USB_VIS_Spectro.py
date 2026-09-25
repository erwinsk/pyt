import sys
import os
import serial
import time
import glob
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

# --- Fungsi Mendeteksi Serial Port Otomatis ---
def get_serial_ports():
    if sys.platform.startswith('win'):
        return [f'COM{i+1}' for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        return glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        return glob.glob('/dev/tty.*')
    return []

# --- Worker Thread untuk Komunikasi Serial ---
class DataWorker(QThread):
    data_signal = pyqtSignal(np.ndarray)
    status_signal = pyqtSignal(str)
    latency_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.ser = serial.Serial()
        self.running = True
        self.is_connected = False
        
        self.cmd = b"v00000\r\n"
        self.packet_size = 7388
        self.words = 3694

    def connect_serial(self, port, baud, dtr, rts):
        try:
            if self.ser.is_open: 
                self.ser.close()
            self.ser.port = port
            self.ser.baudrate = baud
            self.ser.dtr = dtr
            self.ser.rts = rts
            self.ser.timeout = 0.05
            self.ser.open()
            self.is_connected = True
            self.status_signal.emit("Connected")
            return True
        except Exception as e:
            self.is_connected = False
            self.status_signal.emit(f"Error: {str(e)}")
            return False

    def run(self):
        while self.running:
            if self.is_connected and self.ser.is_open:
                try:
                    self.ser.reset_input_buffer()
                    
                    # Kirim perintah 3x dengan jeda 1 detik
                    for i in range(3):
                        self.ser.write(self.cmd)
                        self.ser.flush()
                        if i < 2:
                            time.sleep(1.0)
                        if not self.running: break

                    if not self.running: break

                    # Tunggu Balasan
                    packet = bytearray()
                    t_start = time.perf_counter()
                    
                    while time.perf_counter() - t_start < 2.0:
                        n = self.ser.in_waiting
                        if n > 0:
                            packet.extend(self.ser.read(n))
                            if len(packet) >= self.packet_size:
                                break
                        time.sleep(0.005)

                    if len(packet) >= self.packet_size:
                        latency_ms = (time.perf_counter() - t_start) * 1000
                        self.latency_signal.emit(f"{latency_ms:.2f} ms")
                        
                        raw_data = packet[:self.packet_size]
                        arr = np.frombuffer(raw_data, dtype=np.uint8)
                        
                        # FORMAT A (MSB first)
                        d1 = (arr[:self.words].astype(np.uint16) << 8) | arr[self.words:].astype(np.uint16)
                        self.data_signal.emit(d1)
                    else:
                        byte_count = len(packet)
                        self.latency_signal.emit(f"Timeout ({byte_count}/{self.packet_size} b)")
                    
                    time.sleep(1.0)
                    
                except Exception as e:
                    self.is_connected = False
                    self.status_signal.emit("Disconnected (Error)")
                    self.latency_signal.emit("-")
            else:
                time.sleep(0.1)

    def stop(self):
        self.running = False
        self.is_connected = False
        if self.ser.is_open:
            self.ser.close()

# --- UI Utama Aplikasi ---
class SpectroApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Spectro Pro Dashboard - Logger & Plot Settings")
        self.resize(1200, 700)

        self.is_recording = False
        self.save_dir = ""
        self.frame_counter = 0

        # Main Layout
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        
        # Panel Kontrol Kiri (Scrollable jika layar kecil)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(350)
        
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setSpacing(10)
        
        # 1. DEVICE SETTINGS
        ctrl_layout.addWidget(self.create_header("DEVICE SETTINGS"))
        
        self.port_cb = QComboBox()
        self.refresh_ports()
        self.baud_cb = QComboBox()
        self.baud_cb.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_cb.setCurrentText("9600")
        
        ctrl_layout.addWidget(QLabel("Serial Port:"))
        ctrl_layout.addWidget(self.port_cb)
        self.refresh_btn = QPushButton("Refresh Ports")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        ctrl_layout.addWidget(self.refresh_btn)
        
        ctrl_layout.addWidget(QLabel("Baud Rate:"))
        ctrl_layout.addWidget(self.baud_cb)

        self.dtr_check = QCheckBox("Enable DTR")
        self.dtr_check.setChecked(True)
        self.rts_check = QCheckBox("Enable RTS")
        self.rts_check.setChecked(False)
        ctrl_layout.addWidget(self.dtr_check)
        ctrl_layout.addWidget(self.rts_check)
        
        self.connect_btn = QPushButton("Connect Perangkat")
        self.connect_btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; padding: 6px;")
        self.connect_btn.clicked.connect(self.handle_connection)
        ctrl_layout.addWidget(self.connect_btn)
        
        ctrl_layout.addWidget(self.create_line())

        # 2. PLOT SETTINGS (Pengaturan Sumbu X dan Y)
        ctrl_layout.addWidget(self.create_header("PLOT SETTINGS"))
        
        # Pengaturan Sumbu X
        self.auto_x_cb = QCheckBox("Auto Scale X-Axis (Wavelength)")
        self.auto_x_cb.setChecked(True)
        self.auto_x_cb.toggled.connect(self.toggle_plot_settings)
        ctrl_layout.addWidget(self.auto_x_cb)
        
        x_layout = QHBoxLayout()
        self.xmin_spin = QDoubleSpinBox()
        self.xmin_spin.setRange(0, 5000)
        self.xmin_spin.setValue(300)
        
        self.xmax_spin = QDoubleSpinBox()
        self.xmax_spin.setRange(0, 5000)
        self.xmax_spin.setValue(1100)
        
        x_layout.addWidget(QLabel("Min X:"))
        x_layout.addWidget(self.xmin_spin)
        x_layout.addWidget(QLabel("Max X:"))
        x_layout.addWidget(self.xmax_spin)
        ctrl_layout.addLayout(x_layout)

        # Pengaturan Sumbu Y
        self.auto_y_cb = QCheckBox("Auto Scale Y-Axis (Intensity)")
        self.auto_y_cb.setChecked(True)
        self.auto_y_cb.toggled.connect(self.toggle_plot_settings)
        ctrl_layout.addWidget(self.auto_y_cb)
        
        y_layout = QHBoxLayout()
        self.ymin_spin = QDoubleSpinBox()
        self.ymin_spin.setRange(-10000, 100000)
        self.ymin_spin.setValue(0)
        
        self.ymax_spin = QDoubleSpinBox()
        self.ymax_spin.setRange(-10000, 100000)
        self.ymax_spin.setValue(65000)
        
        y_layout.addWidget(QLabel("Min Y:"))
        y_layout.addWidget(self.ymin_spin)
        y_layout.addWidget(QLabel("Max Y:"))
        y_layout.addWidget(self.ymax_spin)
        ctrl_layout.addLayout(y_layout)
        
        self.toggle_plot_settings() # Panggil sekali untuk disable input manual saat awal
        
        ctrl_layout.addWidget(self.create_line())

        # 3. DATA RECORDING
        ctrl_layout.addWidget(self.create_header("DATA RECORDING"))

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold; padding: 6px;")
        self.record_btn.clicked.connect(self.toggle_recording)
        ctrl_layout.addWidget(self.record_btn)

        self.record_status_label = QLabel("Saved: 0 files")
        self.record_status_label.setStyleSheet("font-size: 12px; color: #7F8C8D;")
        ctrl_layout.addWidget(self.record_status_label)

        ctrl_layout.addWidget(self.create_line())
        
        # 4. SYSTEM STATUS
        ctrl_layout.addWidget(self.create_header("SYSTEM STATUS"))
        
        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #7F8C8D;")
        self.latency_label = QLabel("Delay Time: -")
        self.latency_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #2980B9;")
        
        ctrl_layout.addWidget(self.status_label)
        ctrl_layout.addWidget(self.latency_label)
        ctrl_layout.addStretch()

        scroll_area.setWidget(ctrl_widget)
        main_layout.addWidget(scroll_area)

        # Canvas Matplotlib (Kanan)
        self.figure, self.ax = plt.subplots(figsize=(7, 5))
        self.canvas = FigureCanvas(self.figure)
        self.line, = self.ax.plot([], [], color='#E74C3C', linewidth=1.5, label='Spectrum')
        self.ax.grid(True, linestyle='--', alpha=0.6)
        self.ax.set_xlabel("Wavelength (nm)", fontsize=11)
        self.ax.set_ylabel("Intensity", fontsize=11)
        self.ax.set_title("Real-time Spectrometer Graph", fontsize=12, fontweight='bold')
        self.ax.legend()
        
        main_layout.addWidget(self.canvas)
        self.setCentralWidget(central_widget)

        # Inisialisasi Worker
        self.worker = DataWorker()
        self.worker.data_signal.connect(self.update_graph)
        self.worker.status_signal.connect(self.update_status)
        self.worker.latency_signal.connect(self.update_latency)
        self.worker.start()

    def create_header(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #2C3E50; margin-top: 5px;")
        return lbl

    def create_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #BDC3C7;")
        return line

    def toggle_plot_settings(self):
        # Disable/Enable input manual X
        is_auto_x = self.auto_x_cb.isChecked()
        self.xmin_spin.setEnabled(not is_auto_x)
        self.xmax_spin.setEnabled(not is_auto_x)
        
        # Disable/Enable input manual Y
        is_auto_y = self.auto_y_cb.isChecked()
        self.ymin_spin.setEnabled(not is_auto_y)
        self.ymax_spin.setEnabled(not is_auto_y)

    def refresh_ports(self):
        self.port_cb.clear()
        ports = get_serial_ports()
        self.port_cb.addItems(ports)
        if not ports:
            self.port_cb.addItem("No Device Found")

    def handle_connection(self):
        if not self.worker.is_connected:
            port = self.port_cb.currentText()
            baud = int(self.baud_cb.currentText())
            if port == "No Device Found" or not port:
                QMessageBox.warning(self, "Peringatan", "Pilih port serial yang valid!")
                return
                
            success = self.worker.connect_serial(port, baud, self.dtr_check.isChecked(), self.rts_check.isChecked())
            if success:
                self.connect_btn.setText("Disconnect")
                self.connect_btn.setStyleSheet("background-color: #E74C3C; color: white; font-weight: bold; padding: 6px;")
        else:
            if self.is_recording:
                self.toggle_recording()
                
            self.worker.stop()
            self.worker = DataWorker()
            self.worker.data_signal.connect(self.update_graph)
            self.worker.status_signal.connect(self.update_status)
            self.worker.latency_signal.connect(self.update_latency)
            self.worker.start()
            
            self.connect_btn.setText("Connect Perangkat")
            self.connect_btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; padding: 6px;")
            self.update_status("Idle")
            self.latency_label.setText("Delay Time: -")

    def toggle_recording(self):
        if not self.is_recording:
            if not self.worker.is_connected:
                QMessageBox.warning(self, "Peringatan", "Koneksikan perangkat terlebih dahulu sebelum merekam!")
                return
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = f"Spectro_Data_{timestamp}"
            self.save_dir = os.path.join(os.getcwd(), folder_name)
            os.makedirs(self.save_dir, exist_ok=True)
            
            self.is_recording = True
            self.frame_counter = 0
            
            self.record_btn.setText("Stop Recording")
            self.record_btn.setStyleSheet("background-color: #E74C3C; color: white; font-weight: bold; padding: 6px;")
            self.record_status_label.setText(f"Folder: {folder_name}\nSaved: 0 files")
        else:
            self.is_recording = False
            self.record_btn.setText("Start Recording")
            self.record_btn.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold; padding: 6px;")
            QMessageBox.information(self, "Info Perekaman", 
                                    f"Perekaman selesai.\nTotal {self.frame_counter} file CSV berhasil disimpan di:\n{self.save_dir}")

    def update_status(self, status):
        self.status_label.setText(f"Status: {status}")
        if "Connected" in status:
            self.status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #2ECC71;")
        else:
            self.status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #E74C3C;")
            if self.is_recording: self.toggle_recording()

    def update_latency(self, latency_text):
        self.latency_label.setText(f"Delay Time: {latency_text}")

    def update_graph(self, d1):
        points = 1600
        intensity = d1[:points]
        wavelength = d1[points:points*2] / 10.0
        
        # Update Plot Data
        self.line.set_data(wavelength, intensity)
        
        # --- LOGIKA SKALA SUMBU (PLOT SETTINGS) ---
        
        # Sumbu X (Wavelength)
        if self.auto_x_cb.isChecked():
            # Beri padding sedikit agar grafiknya manis
            xmin, xmax = wavelength.min(), wavelength.max()
            self.ax.set_xlim(xmin, xmax)
        else:
            # Gunakan nilai dari SpinBox
            self.ax.set_xlim(self.xmin_spin.value(), self.xmax_spin.value())

        # Sumbu Y (Intensity)
        if self.auto_y_cb.isChecked():
            # Beri padding atas dan bawah agar puncak grafik tidak terpotong
            ymin, ymax = intensity.min(), intensity.max()
            padding = (ymax - ymin) * 0.1 # 10% ruang ekstra
            if padding == 0: padding = 10 # Jika data rata
            self.ax.set_ylim(ymin - padding, ymax + padding)
        else:
            # Gunakan nilai dari SpinBox
            self.ax.set_ylim(self.ymin_spin.value(), self.ymax_spin.value())

        self.canvas.draw()

        # Proses Perekaman Data 
        if self.is_recording:
            self.frame_counter += 1
            filename = os.path.join(self.save_dir, f"spectrum_{self.frame_counter:04d}.csv")
            data_to_save = np.column_stack((wavelength, intensity))
            np.savetxt(filename, data_to_save, delimiter=",", 
                       header="Wavelength(nm),Intensity", comments="", fmt="%.2f,%.0f")
            
            folder_name = os.path.basename(self.save_dir)
            self.record_status_label.setText(f"Folder: {folder_name}\nSaved: {self.frame_counter} files")

    def closeEvent(self, event):
        if self.is_recording:
            self.is_recording = False
        self.worker.stop()
        self.worker.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SpectroApp()
    window.show()
    sys.exit(app.exec_())
