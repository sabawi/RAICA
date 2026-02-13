# src/main_window.py
"""
Main window for the application.

This file provides a single :class:`MainWindow` class that inherits from
:class:`QtWidgets.QMainWindow`.  It uses a plain text editor as the
central widget, a file‑open dialog, and a few common actions (Open, Quit,
About).  The layout and signals are set up in the constructor, so the
class can be instantiated directly in ``src/main.py`` or anywhere else
in the project.

The implementation is deliberately lightweight, but it can be extended by
adding more widgets, actions, or a more sophisticated UI definition
(e.g. loading a .ui file created with Qt Designer).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Use PySide6 if it is available, otherwise fall back to PyQt5 (so the module
# works with either library).  The two APIs are largely compatible.
try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PyQt5 import QtCore, QtGui, QtWidgets

# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #

def resource_path(name: str) -> Path:
    """
    Resolve a file relative to the source tree or a PyInstaller bundle.

    Parameters
    ----------
    name:
        filename relative to the directory containing ``main_window.py``

    Returns
    -------
    Path
        Expandable path that works in normal development and in a
        bundled/distributed environment.
    """
    # The directory containing this file
    base_dir = Path(__file__).resolve().parent
    return base_dir / name

# --------------------------------------------------------------------------- #
# MainWindow
# --------------------------------------------------------------------------- #

class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window.

    Features
    -------
    * Plain text editor in the central widget.
    * File → Open – opens a text file.
    * File → Quit – closes the application.
    * Help → About – shows a brief message box.
    * Status bar shows the current file path (if any).
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Simple Text Editor")

        # ------------------------------------------------------------------
        # Central widget – a simple text editor
        # ------------------------------------------------------------------
        self._editor = QtWidgets.QPlainTextEdit(self)
        self.setCentralWidget(self._editor)

        # ------------------------------------------------------------------
        # Actions
        # ------------------------------------------------------------------
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_status_bar()

        # ------------------------------------------------------------------
        # Signals
        # ------------------------------------------------------------------
        self._editor.document().modificationChanged.connect(self._on_modified)

        # Track the currently opened file.
        self._current_file: Optional[Path] = None

        # Set initial geometry
        self.resize(800, 600)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _create_actions(self) -> None:
        """Create actions used in menus, toolbars and keyboard shortcuts."""

        # Open file
        self.open_act = QtWidgets.QAction("&Open", self)
        self.open_act.setShortcuts(QtGui.QKeySequence.Open)
        self.open_act.setStatusTip("Open an existing text file")
        self.open_act.triggered.connect(self.open_file)

        # Quit
        self.quit_act = QtWidgets.QAction("&Quit", self)
        self.quit_act.setShortcuts(QtGui.QKeySequence.Quit)
        self.quit_act.setStatusTip("Quit the application")
        self.quit_act.triggered.connect(self.close)

        # About
        self.about_act = QtWidgets.QAction("&About", self)
        self.about_act.setStatusTip("Show application information")
        self.about_act.triggered.connect(self.show_about)

    def _create_menus(self) -> None:
        """Create the application menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.open_act)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_act)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.about_act)

    def _create_toolbars(self) -> None:
        """Create the main toolbar (optional, but handy)."""
        file_toolbar = self.addToolBar("File")
        file_toolbar.addAction(self.open_act)
        file_toolbar.addAction(self.quit_act)

    def _create_status_bar(self) -> None:
        """Set up a status bar."""
        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def open_file(self) -> None:
        """Open a text file using a QFileDialog."""
        if self._modified:
            reply = self._prompt_save()
            if not reply:
                return

        dialog = QtWidgets.QFileDialog(self, "Open File")
        dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dialog.setNameFilter("Text Files (*.txt);;All Files (*)")
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return

        file_path = Path(dialog.selectedFiles()[0])
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Error", str(exc))
            return

        self._editor.setPlainText(content)
        self._current_file = file_path
        self._editor.document().setModified(False)
        self.setWindowTitle(f"{file_path.name} – {self.windowTitle()}")
        self.statusBar().showMessage(f"Opened {file_path}", 5000)

    def _prompt_save(self) -> bool:
        """
        Ask the user whether the current document should be saved.

        Returns
        -------
        bool
            ``True`` if the user wants to continue (i.e. discard the
            changes or successfully saved). ``False`` means cancel.
        """
        if not self._modified:
            return True

        ret = QtWidgets.QMessageBox.question(
            self,
            "Unsaved Changes",
            "The document has been modified.\nDo you want to save changes?",
            QtWidgets.QMessageBox.Yes
            | QtWidgets.QMessageBox.No
            | QtWidgets.QMessageBox.Cancel,
        )

        if ret == QtWidgets.QMessageBox.Cancel:
            return False

        if ret == QtWidgets.QMessageBox.Yes:
            return self._save_file_dialog()

        return True

    def _save_file_dialog(self) -> bool:
        """
        Prompt the user for a file name and save the current content.

        Returns
        -------
        bool
            ``True`` if the file was successfully written, otherwise
            ``False``.
        """
        if self._current_file is None:
            return self._save_file_as()

        try:
            with self._current_file.open("w", encoding="utf-8") as f:
                f.write(self._editor.toPlainText())
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Error", str(exc))
            return False

        self._editor.document().setModified(False)
        self.statusBar().showMessage(f"Saved {self._current_file}", 5000)
        return True

    def _save_file_as(self) -> bool:
        """
        Ask the user to choose a file name and save the content there.

        Returns
        -------
        bool
            ``True`` if the file was successfully written.
        """
        dialog = QtWidgets.QFileDialog(self, "Save As")
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.setNameFilter("Text Files (*.txt);;All Files (*)")

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return False

        file_path = Path(dialog.selectedFiles()[0])
        try:
            with file_path.open("w", encoding="utf-8") as f:
                f.write(self._editor.toPlainText())
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Error", str(exc))
            return False

        self._current_file = file_path
        self._editor.document().setModified(False)
        self.setWindowTitle(f"{file_path.name} – {self.windowTitle()}")
        self.statusBar().showMessage(f"Saved {file_path}", 5000)
        return True

    def show_about(self) -> None:
        """Show a very simple About dialog."""
        QtWidgets.QMessageBox.about(
            self,
            "About",
            f"{self.windowTitle()}\n\n"
            "A minimal example of a PySide6/QT main window.\n"
            "© 2024",
        )

    @property
    def _modified(self) -> bool:
        """Convenience accessor for the modified state of the document."""
        return self._editor.document().isModified()

    # ------------------------------------------------------------------
    # Override closeEvent to ask for saving modified documents
    # ------------------------------------------------------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._prompt_save():
            event.accept()
        else:
            event.ignore()

# --------------------------------------------------------------------------- #
# Demo entry‑point
# --------------------------------------------------------------------------- #

def _demo() -> None:
    """Launch a standalone demo of the main window."""
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

# Enable the demo when the module is executed directly
if __name__ == "__main__":  # pragma: no cover
    _demo()