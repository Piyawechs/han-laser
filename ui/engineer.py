"""Engineer mode: หน้า Settings ต้องใส่รหัสผ่านก่อน"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

import han_laser as hl

MIN_LEN = 4


class SetPasswordDialog(QDialog):
    """ตั้งรหัสใหม่ (ถ้ามีรหัสเดิม ต้องใส่รหัสเดิมด้วย)"""

    def __init__(self, parent, current_hash: str):
        super().__init__(parent)
        self.current_hash = current_hash
        self.new_hash = ""
        self.setWindowTitle("ตั้งรหัสผ่าน Engineer mode" if not current_hash else "เปลี่ยนรหัสผ่าน")
        self.old = QLineEdit()
        self.new = QLineEdit()
        self.confirm = QLineEdit()
        for w in (self.old, self.new, self.confirm):
            w.setEchoMode(QLineEdit.Password)
        self.msg = QLabel()
        self.msg.setStyleSheet("color: #d62828;")
        form = QFormLayout()
        if current_hash:
            form.addRow("รหัสเดิม", self.old)
        else:
            form.addRow(QLabel("ยังไม่มีรหัสผ่าน ตั้งรหัสสำหรับเข้า Settings"))
        form.addRow("รหัสใหม่", self.new)
        form.addRow("ยืนยันรหัสใหม่", self.confirm)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.msg)
        lay.addWidget(bb)

    def _ok(self) -> None:
        if self.current_hash and not hl.verify_password(self.old.text(), self.current_hash):
            return self.msg.setText("รหัสเดิมไม่ถูกต้อง")
        if len(self.new.text()) < MIN_LEN:
            return self.msg.setText(f"รหัสใหม่ต้องยาวอย่างน้อย {MIN_LEN} ตัว")
        if self.new.text() != self.confirm.text():
            return self.msg.setText("ยืนยันรหัสไม่ตรงกัน")
        self.new_hash = hl.hash_password(self.new.text())
        self.accept()


class UnlockDialog(QDialog):
    def __init__(self, parent, current_hash: str):
        super().__init__(parent)
        self.current_hash = current_hash
        self.setWindowTitle("Engineer mode")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.msg = QLabel()
        self.msg.setStyleSheet("color: #d62828;")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("ใส่รหัสผ่าน Engineer"))
        lay.addWidget(self.pw)
        lay.addWidget(self.msg)
        lay.addWidget(bb)

    def _ok(self) -> None:
        if hl.verify_password(self.pw.text(), self.current_hash):
            self.accept()
        else:
            self.msg.setText("รหัสผ่านไม่ถูกต้อง")
            self.pw.selectAll()
            self.pw.setFocus()


class LockPage(QWidget):
    unlock_requested = Signal()

    def __init__(self):
        super().__init__()
        title = QLabel("Settings สำหรับ Engineer เท่านั้น")
        tf = QFont()
        tf.setPointSize(14)
        tf.setBold(True)
        title.setFont(tf)
        self.hint = QLabel()
        self.hint.setStyleSheet("color: #6b7280;")
        btn = QPushButton("เข้าสู่ Engineer mode")
        btn.setMinimumHeight(40)
        btn.setFixedWidth(240)
        btn.clicked.connect(self.unlock_requested)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        for w in (title, self.hint, btn):
            lay.addWidget(w, 0, Qt.AlignHCenter)
        lay.addStretch(2)

    def set_has_password(self, has: bool) -> None:
        self.hint.setText("ใส่รหัสผ่านเพื่อแก้ไขการตั้งค่า" if has
                          else "ยังไม่ได้ตั้งรหัสผ่าน กดปุ่มเพื่อตั้งรหัสครั้งแรก")
