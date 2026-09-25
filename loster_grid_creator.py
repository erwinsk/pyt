import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QFileDialog, QSpinBox, 
                             QLabel, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QPainter, QImage

class ClickablePixmapItem(QGraphicsPixmapItem):
    def __init__(self, pixmap, row, col, parent_app):
        super().__init__(pixmap)
        self.row = row
        self.col = col
        self.parent_app = parent_app
        self.setTransformationMode(Qt.SmoothTransformation)
        self.setTransformOriginPoint(pixmap.width() / 2, pixmap.height() / 2)

    def mousePressEvent(self, event):
        new_rotation = self.rotation() + 90
        self.setRotation(new_rotation)
        self.parent_app.rotation_data[(self.row, self.col)] = new_rotation
        super().mousePressEvent(event)

class ImageGridApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Grid Image Master - Final White BG")
        self.resize(1200, 800)
        self.image_path = None
        self.rotation_data = {} 
        self.initUI()

    def initUI(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        controls = QHBoxLayout()
        
        self.btn_upload = QPushButton("1. Upload")
        self.btn_upload.clicked.connect(self.upload_image)
        
        self.spin_width = QSpinBox()
        self.spin_width.setRange(1, 50); self.spin_width.setValue(3)
        self.spin_width.valueChanged.connect(self.generate_grid)
        
        self.spin_height = QSpinBox()
        self.spin_height.setRange(1, 50); self.spin_height.setValue(3)
        self.spin_height.valueChanged.connect(self.generate_grid)

        self.spin_size = QSpinBox()
        self.spin_size.setRange(20, 1000); self.spin_size.setValue(100)
        self.spin_size.setSuffix(" px")
        self.spin_size.valueChanged.connect(self.generate_grid)

        self.spin_padding = QSpinBox()
        self.spin_padding.setRange(0, 500); self.spin_padding.setValue(10)
        self.spin_padding.setSuffix(" px")
        self.spin_padding.valueChanged.connect(self.generate_grid)

        self.btn_save = QPushButton("2. Simpan Gambar")
        self.btn_save.clicked.connect(self.save_composite_image)
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")

        controls.addWidget(self.btn_upload)
        controls.addWidget(QLabel("Kolom:"))
        controls.addWidget(self.spin_width)
        controls.addWidget(QLabel("Baris:"))
        controls.addWidget(self.spin_height)
        controls.addWidget(QLabel("Ukuran:"))
        controls.addWidget(self.spin_size)
        controls.addWidget(QLabel("Padding:"))
        controls.addWidget(self.spin_padding)
        controls.addSpacing(20)
        controls.addWidget(self.btn_save)
        controls.addStretch()

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Mengatur background view menjadi putih
        self.view.setStyleSheet("background-color: white;") 

        layout.addLayout(controls)
        layout.addWidget(self.view)

    def upload_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Pilih Gambar", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            self.image_path = file_path
            self.rotation_data.clear()
            self.generate_grid()

    def generate_grid(self):
        if not self.image_path: return
        self.scene.clear()
        
        original_pixmap = QPixmap(self.image_path)
        img_size = self.spin_size.value()
        scaled_pixmap = original_pixmap.scaled(img_size, img_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        
        w_count = self.spin_width.value()
        h_count = self.spin_height.value()
        padding = self.spin_padding.value()
        
        for row in range(h_count):
            for col in range(w_count):
                item = ClickablePixmapItem(scaled_pixmap, row, col, self)
                
                if (row, col) in self.rotation_data:
                    item.setRotation(self.rotation_data[(row, col)])
                else:
                    self.rotation_data[(row, col)] = 0
                
                x_pos = col * (img_size + padding)
                y_pos = row * (img_size + padding)
                item.setPos(x_pos, y_pos)
                self.scene.addItem(item)

        self.scene.setSceneRect(self.scene.itemsBoundingRect())

    def save_composite_image(self):
        if not self.scene.items(): return
        
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty(): return

        # Format RGB32 sudah cukup karena kita tidak butuh transparansi (Alpha)
        image = QImage(rect.size().toSize(), QImage.Format_RGB32)
        
        # PERBAIKAN: Isi background dengan warna Putih sebelum rendering
        image.fill(Qt.white) 

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.scene.render(painter)
        painter.end()

        file_path, _ = QFileDialog.getSaveFileName(self, "Simpan Gambar", "hasil_grid.jpg", "JPG Files (*.jpg);;PNG Files (*.png)")
        if file_path:
            # Kualitas 100 untuk hasil terbaik
            image.save(file_path, quality=100)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageGridApp()
    window.show()
    sys.exit(app.exec_())