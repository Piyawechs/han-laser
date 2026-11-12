"""หน้า Verify: สแกน serial หลังมาร์ก ตรวจกับ DB และเก็บประวัติ"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import han_laser as hl
from ui.common import error

PLACEHOLDER = "— เลือก —"
GREEN, RED, GREY = "#15803d", "#b91c1c", "#6b7280"
REASON_TH = {"NOT_FOUND": "ไม่พบในระบบ", "WRONG_WORKORDER": "ผิด Workorder", "DUPLICATE": "ซ้ำ", "": ""}


def big_font(size: int, bold: bool = True) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    return f


class VerifyTab(QWidget):
    verified = Signal()
    COLS = ["เวลา", "Serial", "ผล", "สาเหตุ", "EN", "Shift", "Workorder"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.session_pass = self.session_fail = 0

        # ---- เลือก EN / Shift / Workorder
        self.en = QComboBox()
        self.shift = QComboBox()
        self.workorder = QComboBox()
        for c in (self.en, self.shift, self.workorder):
            c.setMinimumWidth(160)
            c.setMinimumHeight(32)
            c.setFont(big_font(12, False))
        sel = QHBoxLayout()
        for label, w in (("EN", self.en), ("Shift", self.shift), ("Workorder", self.workorder)):
            lbl = QLabel(label)
            lbl.setFont(big_font(12))
            sel.addWidget(lbl)
            sel.addWidget(w, 1)
            sel.addSpacing(12)

        # ---- ช่องสแกน
        self.scan = QLineEdit()
        self.scan.setFont(big_font(20))
        self.scan.setMinimumHeight(56)
        self.scan.setAlignment(Qt.AlignCenter)
        self.scan_hint = QLabel()
        self.scan_hint.setStyleSheet(f"color: {GREY};")
        self.scan_hint.setAlignment(Qt.AlignCenter)

        # ---- ผลลัพธ์
        self.result_box = QFrame()
        self.result_box.setMinimumHeight(150)
        self.result_word = QLabel()
        self.result_word.setFont(big_font(40))
        self.result_word.setAlignment(Qt.AlignCenter)
        self.result_serial = QLabel()
        self.result_serial.setFont(big_font(18))
        self.result_serial.setAlignment(Qt.AlignCenter)
        self.result_msg = QLabel()
        self.result_msg.setFont(big_font(12, False))
        self.result_msg.setAlignment(Qt.AlignCenter)
        self.result_msg.setWordWrap(True)
        rl = QVBoxLayout(self.result_box)
        for w in (self.result_word, self.result_serial, self.result_msg):
            rl.addWidget(w)

        # ---- ตัวนับ
        self.stat_wo = QLabel()
        self.stat_session = QLabel()
        for s in (self.stat_wo, self.stat_session):
            s.setFont(big_font(11, False))
        stats = QGridLayout()
        stats.addWidget(self.stat_wo, 0, 0)
        stats.addWidget(self.stat_session, 0, 1, Qt.AlignRight)

        # ---- ประวัติล่าสุด
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setFocusPolicy(Qt.NoFocus)              # ไม่แย่ง focus จากช่องสแกน
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)

        lay = QVBoxLayout(self)
        lay.addLayout(sel)
        lay.addSpacing(6)
        lay.addWidget(self.scan)
        lay.addWidget(self.scan_hint)
        lay.addWidget(self.result_box)
        lay.addLayout(stats)
        lay.addWidget(QLabel("ประวัติการ verify ล่าสุด (Workorder ที่เลือก)"))
        lay.addWidget(self.table, 1)

        for c in (self.en, self.shift, self.workorder):
            c.currentIndexChanged.connect(self._selection_changed)
        self.scan.returnPressed.connect(self.do_verify)
        self._show_idle()

    # ------------------------------------------------------------
    def reload(self) -> None:
        app = self.win.app
        for combo, items in ((self.en, app.operators), (self.shift, app.shifts),
                             (self.workorder, app.workorders)):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(PLACEHOLDER, None)
            for it in items:
                combo.addItem(it, it)
            idx = combo.findData(cur) if cur is not None else -1
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)
        self._selection_changed()

    def selection(self) -> tuple[str | None, str | None, str | None]:
        return self.en.currentData(), self.shift.currentData(), self.workorder.currentData()

    def ready(self) -> bool:
        return all(self.selection())

    def _selection_changed(self) -> None:
        ok = self.ready()
        self.scan.setEnabled(ok)
        if ok:
            self.scan.setPlaceholderText("สแกน QR code ที่นี่")
            self.scan_hint.setText("สแกนแล้วระบบตรวจทันที (เครื่องสแกนกด Enter ให้เอง)")
            self.focus_scan()
        else:
            missing = [n for n, v in zip(("EN", "Shift", "Workorder"), self.selection()) if not v]
            self.scan.setPlaceholderText("เลือก " + ", ".join(missing) + " ก่อน")
            app = self.win.app
            if not (app.operators and app.workorders):
                self.scan_hint.setText("ยังไม่มีรายการ EN / Workorder ให้ Engineer เพิ่มในหน้า Settings")
            else:
                self.scan_hint.setText("")
        self.refresh()

    def focus_scan(self) -> None:
        if self.scan.isEnabled():
            QTimer.singleShot(0, self.scan.setFocus)

    def _show_idle(self) -> None:
        self.result_box.setStyleSheet(f"QFrame {{ background: #f3f4f6; border-radius: 10px; }}")
        self.result_word.setText("READY")
        self.result_word.setStyleSheet(f"color: {GREY};")
        self.result_serial.setText("")
        self.result_msg.setText("")

    def _show_result(self, r: hl.VerifyResult) -> None:
        color = GREEN if r.ok else RED
        self.result_box.setStyleSheet(f"QFrame {{ background: {color}; border-radius: 10px; }}")
        for w in (self.result_word, self.result_serial, self.result_msg):
            w.setStyleSheet("color: white;")
        self.result_word.setText("PASS" if r.ok else "FAIL")
        self.result_serial.setText(r.serial)
        self.result_msg.setText(r.message)

    def do_verify(self) -> None:
        raw = self.scan.text()
        self.scan.clear()
        if not self.ready() or not raw.strip():
            return self.focus_scan()
        en, shift, wo = self.selection()
        try:
            r = hl.verify(self.win.store, raw, en, shift, wo)
        except (ValueError, OSError) as e:
            error(self, f"บันทึกผลไม่ได้\n\n{e}")
            return self.focus_scan()
        if r.ok:
            self.session_pass += 1
        else:
            self.session_fail += 1
            QApplication.beep()
        self._show_result(r)
        self.refresh()
        self.verified.emit()
        self.focus_scan()

    def refresh(self) -> None:
        wo = self.workorder.currentData()
        store = self.win.store
        if wo:
            s = store.workorder_stats(wo)
            self.stat_wo.setText(f"Workorder <b>{wo}</b>: ผ่านแล้ว <b>{s['passed']}</b> / generate {s['generated']}"
                                 f"  ·  FAIL {s['failed']} ครั้ง")
        else:
            self.stat_wo.setText("")
        self.stat_session.setText(f"รอบนี้: <b style='color:{GREEN}'>PASS {self.session_pass}</b>"
                                  f"  <b style='color:{RED}'>FAIL {self.session_fail}</b>")
        rows = store.list_verifications(wo) if wo else []
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = [row["scanned_at"].replace("T", " "), row["serial"], row["result"],
                    REASON_TH.get(row["reason"], row["reason"]), row["en"], row["shift"], row["workorder"]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 2:
                    item.setForeground(Qt.white)
                    item.setBackground(Qt.darkGreen if v == "PASS" else Qt.darkRed)
                self.table.setItem(r, c, item)
