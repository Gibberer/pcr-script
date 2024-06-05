import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QFileDialog, QMessageBox
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage
from PyQt6.QtCore import Qt, QRect, QPoint
from aqt import QPaintEvent
from pcrscript import DNSimulator
from pcrscript.driver import Driver
import yaml
import cv2 as cv


class Screenshot(QLabel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.begin:QPoint = None
        self.end:QPoint = None

    def setPixmap(self, a0: QPixmap) -> None:
        self.begin = None
        self.end = None
        return super().setPixmap(a0)
    
    def mousePressEvent(self, event):
        if self.pixmap().isNull():
            return
        self.begin = event.position().toPoint()
        self.end = self.begin
        self.update()

    def mouseMoveEvent(self, event):
        if self.pixmap().isNull():
            return
        self.end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):
        if self.pixmap().isNull():
            return
        self.end = event.position().toPoint()
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        super().paintEvent(event)
        if self.pixmap().isNull():
            return
        if not self.begin or not self.end:
            return
        painter = QPainter(self)
        brush_color = (255, 0, 0, 100)  # 红色，透明度100
        lw = 3
        pen = QPen(QColor(*brush_color), lw, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawText(self.begin, f"({self.begin.x()},{self.begin.y()})")
        painter.drawText(self.end, f"({self.end.x()},{self.end.y()})")
        rect = QRect(self.begin, self.end)
        painter.drawRect(rect)

class SnipTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.driver:Driver = None

    def initUI(self):
        self.setWindowTitle('截图工具')
        w = 980
        h = 580
        self.setGeometry(0, 0, w, h)
        center = self.screen().availableGeometry().center()
        self.move(center.x() - w//2, center.y() - h//2)

        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        btn_snip = QPushButton('获取截图')
        btn_snip.clicked.connect(self.start_snipping)
        btn_export = QPushButton('导出截图')
        btn_export.clicked.connect(self.export)
        hlayout.addWidget(btn_snip)
        hlayout.addWidget(btn_export)

        self.label_image = Screenshot()
        layout.addLayout(hlayout)
        layout.addWidget(self.label_image)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
    
    def export(self):
        lt = self.label_image.begin
        rb = self.label_image.end
        if lt is None or rb is None:
            QMessageBox.warning(self, "Warn", "未设置截取区域")
            return
        cropped = self.label_image.pixmap().copy(QRect(lt, rb))
        fileName, _ = QFileDialog.getSaveFileName(self, "导出截图", "images", "Image Files (*.png)")
        if fileName:
            cropped.save(fileName, "PNG")

    def start_snipping(self):
        if not self.driver:
            with open("daily_config.yml", encoding="utf-8") as f:
                config = yaml.load(f, Loader=yaml.FullLoader)
            self.driver = DNSimulator(path=config["Extra"]["dnpath"], useADB=False).get_dirvers()[0]
        screenshot = cv.cvtColor(self.driver.screenshot(), cv.COLOR_BGR2RGB)
        self.label_image.setPixmap(QPixmap(QImage(screenshot, screenshot.shape[1], screenshot.shape[0],QImage.Format.Format_RGB888)))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = SnipTool()
    ex.show()
    sys.exit(app.exec())