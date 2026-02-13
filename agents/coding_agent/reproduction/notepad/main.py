
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget

from PyQt6.QtGui import QPainter, QColor, QPaintEvent
from PyQt6.QtCore import QRect

class LinedTextEdit(QTextEdit):
    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setPen(QColor("red"))
        
        # Draw lines logic (simplified)
        count = self.document().blockCount()
        painter.drawLine(0, 0, 100, 100) # Dummy line

class Notepad(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Notepad")
        self.setGeometry(100, 100, 600, 400)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.text_edit = LinedTextEdit()
        self.layout.addWidget(self.text_edit)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Notepad()
    window.show()
    sys.exit(app.exec())
