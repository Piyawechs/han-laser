from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

import han_laser as hl
from ui.common import ImageLabel, error, rel_or_abs


def lines_of(edit: QPlainTextEdit) -> list[str]:
    """แยกบรรทัด ตัดช่องว่าง ตัดบรรทัดว่างและรายการซ้ำ (คงลำดับเดิม)"""
    out = []
    for line in edit.toPlainText().splitlines():
        s = line.strip()
        if s and s not in out:
            out.append(s)
    return out


class PathEdit(QWidget):
    """ช่อง path + ปุ่ม Browse"""

    def __init__(self, base_dir, filt: str, save: bool = False):
        super().__init__()
        self.base_dir, self.filt, self.save = base_dir, filt, save
        self.edit = QLineEdit()
        btn = QPushButton("Browse…")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)
        btn.clicked.connect(self.browse)

    def browse(self) -> None:
        base = self.base_dir()
        start = str(base / self.edit.text()) if self.edit.text() else str(base)
        fn = (QFileDialog.getSaveFileName if self.save else QFileDialog.getOpenFileName)(
            self, "เลือกไฟล์", start, self.filt)[0]
        if fn:
            self.edit.setText(rel_or_abs(fn, base))

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, t: str) -> None:
        self.edit.setText(t)


class SettingsTab(QWidget):
    saved = Signal(object)  # AppConfig ใหม่
    change_password_requested = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.work: hl.AppConfig | None = None   # สำเนาที่กำลังแก้ ยังไม่ save
        self.cur_id: str | None = None

        # ---- รายการ product
        self.list = QListWidget()
        add = QPushButton("+ เพิ่ม product")
        remove = QPushButton("ลบ")
        lbox = QVBoxLayout()
        lbox.addWidget(QLabel("Products"))
        lbox.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        lbox.addLayout(row)
        left = QWidget()
        left.setLayout(lbox)
        left.setFixedWidth(220)

        # ---- ฟอร์ม product
        base = lambda: self.win.config_path.resolve().parent  # noqa: E731
        self.id_lbl = QLabel()
        self.name = QLineEdit()
        self.prefix = QLineEdit()
        self.fmt = QLineEdit()
        self.fmt.setToolTip("{prefix} {date:%y%m} {seq:04d}  (date ใช้รูปแบบ strftime)")
        self.reset = QComboBox()
        self.reset.addItems(list(hl.PERIOD_FORMATS))
        self.seq_start = QSpinBox()
        self.seq_start.setRange(0, 10**9)
        self.seq_max = QSpinBox()
        self.seq_max.setRange(1, 10**9)
        self.example = QLabel()
        self.template = PathEdit(base, "Han's template (*.hs);;All files (*)")
        self.txt = PathEdit(base, "Text (*.txt)", save=True)
        self.exe = PathEdit(base, "Program (*.exe);;All files (*)")
        self.exe.edit.setPlaceholderText("ว่าง = เปิด .hs ด้วยโปรแกรมที่ Windows ผูกไว้")
        self.image_path = PathEdit(base, "Images (*.png *.jpg *.jpeg *.bmp)")
        self.image = ImageLabel()
        self.image.setMinimumSize(200, 150)
        self.image.setMaximumHeight(220)

        pform = QFormLayout()
        pform.addRow("ID", self.id_lbl)
        pform.addRow("ชื่อ", self.name)
        pform.addRow("Prefix", self.prefix)
        pform.addRow("รูปแบบ serial", self.fmt)
        pform.addRow("เริ่มเลขใหม่", self.reset)
        pform.addRow("เลขเริ่มต้น", self.seq_start)
        pform.addRow("เลขสูงสุด", self.seq_max)
        pform.addRow("ตัวอย่าง", self.example)
        pform.addRow("Template (.hs)", self.template)
        pform.addRow("ไฟล์ serial .txt", self.txt)
        pform.addRow("โปรแกรมมาร์ก", self.exe)
        pform.addRow("รูปตำแหน่งมาร์ก", self.image_path)
        pform.addRow("", self.image)
        pbox = QGroupBox("Product")
        pbox.setLayout(pform)

        # ---- ค่ารวม
        self.encoding = QComboBox()
        self.encoding.setEditable(True)
        self.encoding.addItems(["utf-8", "utf-8-sig", "ascii", "cp874", "gbk"])
        gform = QFormLayout()
        gform.addRow("Encoding ไฟล์ .txt", self.encoding)
        gbox = QGroupBox("ทั่วไป")
        gbox.setLayout(gform)

        # ---- รายการ dropdown ของหน้า Verify (บรรทัดละ 1 รายการ)
        self.operators = QPlainTextEdit()
        self.shifts = QPlainTextEdit()
        self.workorders = QPlainTextEdit()
        self.iqr_codes = QPlainTextEdit()
        vrow = QHBoxLayout()
        for title, w in (("EN (พนักงาน)", self.operators), ("Shift", self.shifts),
                         ("Workorder (= Lot ตอน Generate)", self.workorders), ("iQR code", self.iqr_codes)):
            w.setMinimumHeight(160)
            w.setPlaceholderText("บรรทัดละ 1 รายการ")
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            col.addWidget(w)
            vrow.addLayout(col)
        vbox = QGroupBox("รายการ dropdown หน้า Verify")
        vbox.setLayout(vrow)

        save = QPushButton("บันทึก")
        save.setMinimumHeight(36)
        save.setStyleSheet("QPushButton { font-weight: bold; }")
        revert = QPushButton("ยกเลิกการแก้")
        chpw = QPushButton("เปลี่ยนรหัสผ่าน Engineer")
        chpw.clicked.connect(self.change_password_requested)
        brow = QHBoxLayout()
        brow.addWidget(chpw)
        brow.addStretch(1)
        brow.addWidget(revert)
        brow.addWidget(save)

        # แท็บย่อย: Products | Verify และทั่วไป
        page1 = QWidget()
        p1 = QHBoxLayout(page1)
        p1.addWidget(left)
        p1.addWidget(pbox, 1)
        page2 = QWidget()
        p2 = QVBoxLayout(page2)
        p2.addWidget(vbox)
        p2.addWidget(gbox)
        p2.addStretch(1)
        inner = QTabWidget()
        inner.addTab(page1, "Products")
        inner.addTab(page2, "Verify และทั่วไป")

        lay = QVBoxLayout(self)
        lay.addWidget(inner, 1)
        lay.addLayout(brow)

        self.list.currentItemChanged.connect(self._select)
        add.clicked.connect(self.add_product)
        remove.clicked.connect(self.remove_product)
        save.clicked.connect(self.save)
        revert.clicked.connect(self.reload)
        for w in (self.prefix, self.fmt):
            w.textChanged.connect(self._update_example)
        for w in (self.seq_start,):
            w.valueChanged.connect(self._update_example)
        self.reset.currentIndexChanged.connect(self._update_example)
        self.image_path.edit.textChanged.connect(self._update_image)

    # ------------------------------------------------------------
    def reload(self) -> None:
        self.work = copy.deepcopy(self.win.app)
        self.cur_id = None
        self.encoding.setCurrentText(self.work.txt_encoding)
        self.operators.setPlainText("\n".join(self.work.operators))
        self.shifts.setPlainText("\n".join(self.work.shifts))
        self.workorders.setPlainText("\n".join(self.work.workorders))
        self.iqr_codes.setPlainText("\n".join(self.work.iqr_codes))
        self._fill_list(self.work.last_product)

    def _fill_list(self, select: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.work.products.values():
            it = QListWidgetItem(f"{p.name}\n  {p.id}")
            it.setData(256, p.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        ids = list(self.work.products)
        self.list.setCurrentRow(ids.index(select) if select in ids else 0)

    def _select(self, cur, _prev) -> None:
        self._commit_form()
        self.cur_id = cur.data(256) if cur else None
        if self.cur_id:
            self._load_form(self.work.products[self.cur_id])

    def _load_form(self, p: hl.Product) -> None:
        self.id_lbl.setText(p.id)
        self.name.setText(p.name)
        self.prefix.setText(p.prefix)
        self.fmt.setText(p.serial_format)
        self.reset.setCurrentText(p.seq_reset)
        self.seq_start.setValue(p.seq_start)
        self.seq_max.setValue(p.seq_max)
        self.template.setText(p.template)
        self.txt.setText(p.serial_txt)
        self.exe.setText(p.marking_exe)
        self.image_path.setText(p.image)
        self._update_example()
        self._update_image()

    def _commit_form(self) -> None:
        """เอาค่าจากฟอร์มใส่สำเนา (ยังไม่ save ลงไฟล์)"""
        if not self.cur_id or self.cur_id not in self.work.products:
            return
        p = self.work.products[self.cur_id]
        p.name = self.name.text().strip()
        p.prefix = self.prefix.text().strip()
        p.serial_format = self.fmt.text().strip()
        p.seq_reset = self.reset.currentText()
        p.seq_start = self.seq_start.value()
        p.seq_max = self.seq_max.value()
        p.template = self.template.text()
        p.serial_txt = self.txt.text()
        p.marking_exe = self.exe.text()
        p.image = self.image_path.text()

    def _update_example(self) -> None:
        p = hl.Product(id="x", name="x", template="x", serial_txt="x", prefix=self.prefix.text().strip(),
                       serial_format=self.fmt.text().strip(), seq_reset=self.reset.currentText(),
                       seq_start=self.seq_start.value(), seq_max=max(self.seq_max.value(), self.seq_start.value()))
        try:
            p.validate()
            self.example.setText(f"<b>{p.format_serial(datetime.now(), p.seq_start)}</b>")
        except ValueError as e:
            self.example.setText(f"<span style='color:#d62828'>{str(e).split(': ', 1)[-1]}</span>")

    def _update_image(self) -> None:
        t = self.image_path.text()
        self.image.set_image(self.work.abspath(t) if (t and self.work) else None)

    # ------------------------------------------------------------
    def add_product(self) -> None:
        self._commit_form()
        pid, ok = QInputDialog.getText(self, "เพิ่ม product", "ID (a-z 0-9 _ เปลี่ยนภายหลังไม่ได้):")
        pid = pid.strip().lower()
        if not ok or not pid:
            return
        if not hl.PRODUCT_ID_RE.match(pid) or pid in self.work.products:
            return error(self, f"ID '{pid}' ใช้ไม่ได้ หรือมีอยู่แล้ว")
        self.work.products[pid] = hl.Product(
            id=pid, name=pid.replace("_", " ").title(), prefix=pid[:2].upper(),
            template=f"{pid}.hs", serial_txt=f"serial_{pid}.txt")
        self._fill_list(pid)

    def remove_product(self) -> None:
        if not self.cur_id:
            return
        if len(self.work.products) == 1:
            return error(self, "ต้องมีอย่างน้อย 1 product")
        if QMessageBox.question(self, "ลบ product",
                                f"ลบ '{self.cur_id}' ออกจาก config?\n(ประวัติใน database ยังอยู่)") != QMessageBox.Yes:
            return
        del self.work.products[self.cur_id]
        self.cur_id = None
        self._fill_list()

    def save(self) -> None:
        self._commit_form()
        self.work.txt_encoding = self.encoding.currentText().strip()
        self.work.operators = lines_of(self.operators)
        self.work.shifts = lines_of(self.shifts)
        self.work.workorders = lines_of(self.workorders)
        self.work.iqr_codes = lines_of(self.iqr_codes)
        if self.work.last_product not in self.work.products:
            self.work.last_product = next(iter(self.work.products))
        try:
            self.work.save(self.win.config_path)
        except (ValueError, OSError) as e:
            return error(self, f"บันทึกไม่ได้\n\n{e}")
        self.saved.emit(copy.deepcopy(self.work))
        QMessageBox.information(self, "Settings", "บันทึกแล้ว")
