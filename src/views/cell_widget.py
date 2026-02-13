from PyQt5.QtWidgets import QWidget

class CellWidget(QWidget):
    def __init__(self, name: str = ""):
        super().__init__()
        self.name = name