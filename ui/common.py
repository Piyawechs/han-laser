from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QMessageBox, QSizePolicy, QWidget


def error(parent: QWidget, msg: str, title: str = "ผิดพลาด") -> None:
    QMessageBox.critical(parent, title, msg)


def rel_or_abs(path: str, base: Path) -> str:
    """เก็บ path แบบ relative ถ้าอยู่ใต้โฟลเดอร์ของ config (ย้ายโฟลเดอร์ได้) ไม่งั้นเก็บเต็ม"""
    p = Path(path).resolve()
    try:
        return p.relative_to(base.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


class ImageLabel(QLabel):
    """แสดงรูปให้พอดีกรอบ คงสัดส่วน"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(240, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("QLabel { background: #f4f5f7; border: 1px solid #d0d4da; }")

    def set_image(self, path: Path | None) -> None:
        self._pix = QPixmap(str(path)) if path and os.path.exists(path) else QPixmap()
        if self._pix.isNull():
            self.setText("(ไม่มีรูป)\n" + (str(path) if path else "ตั้งค่ารูปได้ในหน้า Settings"))
        self._rescale()

    def _rescale(self) -> None:
        if not self._pix.isNull():
            self.setPixmap(self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()
