from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

import han_laser as hl
from store import Store
from ui.common import ImageLabel, error
from ui.engineer import LockPage, SetPasswordDialog, UnlockDialog
from ui.settings_tab import SettingsTab


class GenerateTab(QWidget):
    generated = Signal()

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win

        self.image = ImageLabel()

        self.product = QComboBox()
        self.product.setMinimumWidth(220)
        self.format_lbl = QLabel()
        self.format_lbl.setStyleSheet("color: #6b7280;")
        self.format_lbl.setWordWrap(True)
        self.next_lbl = QLabel()
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self.next_lbl.setFont(f)
        self.next_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.lot = QLineEdit()
        self.lot.setPlaceholderText("เช่น LOT001")
        self.count = QSpinBox()
        self.count.setRange(1, 9999)
        self.count.setValue(100)
        self.range_lbl = QLabel()
        self.range_lbl.setWordWrap(True)

        self.gen_btn = QPushButton("Generate serial")
        self.gen_btn.setMinimumHeight(44)
        self.gen_btn.setStyleSheet(
            "QPushButton { background: #1d4ed8; color: white; font-weight: bold; font-size: 15px;"
            " border-radius: 6px; } QPushButton:disabled { background: #9ca3af; }")
        self.launch_btn = QPushButton("เปิด template (.hs)")
        self.launch_btn.setMinimumHeight(36)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(110)
        self.result.setPlaceholderText("ผลการ generate ล่าสุด")

        form = QFormLayout()
        form.addRow("Product", self.product)
        form.addRow("รูปแบบ", self.format_lbl)
        form.addRow("ตัวถัดไป", self.next_lbl)
        form.addRow("Lot", self.lot)
        form.addRow("จำนวน", self.count)
        form.addRow("จะได้", self.range_lbl)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addSpacing(8)
        right.addWidget(self.gen_btn)
        right.addWidget(self.launch_btn)
        right.addSpacing(8)
        right.addWidget(QLabel("ผลล่าสุด"))
        right.addWidget(self.result)
        right.addStretch(1)
        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setFixedWidth(400)

        lay = QHBoxLayout(self)
        lay.addWidget(self.image, 1)
        lay.addWidget(right_w)

        self.product.currentIndexChanged.connect(self._product_changed)
        self.lot.textChanged.connect(self.update_preview)
        self.count.valueChanged.connect(self.update_preview)
        self.gen_btn.clicked.connect(self.do_generate)
        self.launch_btn.clicked.connect(self.do_launch)

    # ------------------------------------------------------------
    def reload(self) -> None:
        app = self.win.app
        cur = self.product.currentData() or app.last_product
        self.product.blockSignals(True)
        self.product.clear()
        for p in app.products.values():
            self.product.addItem(f"{p.name}  ({p.id})", p.id)
        idx = self.product.findData(cur)
        self.product.setCurrentIndex(idx if idx >= 0 else 0)
        self.product.blockSignals(False)
        self._product_changed()

    def current(self) -> hl.Product:
        return self.win.app.product(self.product.currentData())

    def _product_changed(self) -> None:
        if self.product.currentData() is None:
            return
        app, prod = self.win.app, self.current()
        self.image.set_image(app.abspath(prod.image) if prod.image else None)
        reset = {"daily": "เริ่มใหม่ทุกวัน", "monthly": "เริ่มใหม่ทุกเดือน", "never": "นับต่อเนื่อง"}[prod.seq_reset]
        self.format_lbl.setText(f"{prod.serial_format}  ·  prefix {prod.prefix}  ·  {reset}")
        self.count.setMaximum(max(1, prod.seq_max - prod.seq_start + 1))
        if app.last_product != prod.id:
            app.last_product = prod.id
            try:
                app.save()
            except (ValueError, OSError):
                pass  # จำ product ล่าสุดไม่ได้ ไม่เป็นไร
        self.update_preview()

    def update_preview(self) -> None:
        if self.product.currentData() is None:
            return
        app, store = self.win.app, self.win.store
        try:
            first = hl.preview(app, self.current().id, 1, store=store)[0]
            self.next_lbl.setText(first)
        except ValueError as e:
            self.next_lbl.setText("-")
            self.range_lbl.setText(f"<span style='color:#d62828'>{e}</span>")
            self.gen_btn.setEnabled(False)
            return
        try:
            s = hl.preview(app, self.current().id, self.count.value(), store=store)
            self.range_lbl.setText(f"<b>{s[0]}</b> – <b>{s[-1]}</b>  ({len(s)} ตัว)")
            ok = True
        except ValueError as e:
            self.range_lbl.setText(f"<span style='color:#d62828'>{e}</span>")
            ok = False
        lot_ok = bool(self.lot.text().strip())
        self.gen_btn.setEnabled(ok and lot_ok)
        self.gen_btn.setToolTip("" if lot_ok else "กรอก Lot ก่อน")

    def do_generate(self) -> None:
        app, prod = self.win.app, self.current()
        lot, n = self.lot.text().strip(), self.count.value()
        try:
            s = hl.preview(app, prod.id, n, store=self.win.store)
        except ValueError as e:
            return error(self, str(e))
        txt = app.abspath(prod.serial_txt)
        msg = (f"Product: {prod.name}\nLot: {lot}\nจำนวน: {n}\n{s[0]} – {s[-1]}\n\n"
               f"เขียนทับไฟล์:\n{txt}\n(ไฟล์เดิมจะถูกสำรองไว้ใน archive)")
        if QMessageBox.question(self, "ยืนยัน Generate", msg) != QMessageBox.Yes:
            return
        try:
            b = hl.generate(app, prod.id, n, lot, store=self.win.store)
        except (ValueError, OSError) as e:
            return error(self, f"Generate ไม่สำเร็จ ไม่มีอะไรถูกบันทึก\n\n{e}")
        self.result.setPlainText(
            f"{b.created_at}  [{prod.name}] lot {b.lot}\n"
            f"{len(b.serials)} ตัว: {b.serials[0]} – {b.serials[-1]}\n{b.txt_path}")
        self.update_preview()
        self.generated.emit()

    def do_launch(self) -> None:
        try:
            how = hl.launch(self.win.app, self.current().id)
        except (ValueError, OSError) as e:
            return error(self, str(e))
        self.win.statusBar().showMessage(f"เปิด template ด้วย {how}", 5000)


class HistoryTab(QWidget):
    COLS = ["เวลา", "Product", "Lot", "จำนวน", "ตั้งแต่", "ถึง", "ไฟล์"]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.product = QComboBox()
        self.lot = QLineEdit()
        self.lot.setPlaceholderText("ค้นหา lot")
        refresh = QPushButton("Refresh")

        top = QHBoxLayout()
        top.addWidget(QLabel("Product"))
        top.addWidget(self.product)
        top.addWidget(QLabel("Lot"))
        top.addWidget(self.lot, 1)
        top.addWidget(refresh)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        hint = QLabel("ดับเบิลคลิกแถวเพื่อดู serial ทั้งหมดของชุดนั้น")
        hint.setStyleSheet("color: #6b7280;")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)
        lay.addWidget(hint)

        self.product.currentIndexChanged.connect(self.refresh)
        self.lot.textChanged.connect(self.refresh)
        refresh.clicked.connect(self.refresh)
        self.table.cellDoubleClicked.connect(self.show_batch)

    def reload(self) -> None:
        cur = self.product.currentData()
        self.product.blockSignals(True)
        self.product.clear()
        self.product.addItem("ทั้งหมด", None)
        for p in self.win.app.products.values():
            self.product.addItem(p.name, p.id)
        idx = self.product.findData(cur)
        self.product.setCurrentIndex(max(idx, 0))
        self.product.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        rows = self.win.store.list_batches(self.product.currentData(), self.lot.text().strip() or None)
        names = {pid: p.name for pid, p in self.win.app.products.items()}
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = [row["created_at"].replace("T", " "), names.get(row["product"], row["product"]),
                    row["lot"], str(row["count"]), row["first_serial"], row["last_serial"], row["txt_path"]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.UserRole, row["id"])
                self.table.setItem(r, c, item)

    def show_batch(self, row: int, _col: int = 0) -> None:
        batch_id = self.table.item(row, 0).data(Qt.UserRole)
        serials = self.win.store.serials_of(batch_id)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Serial ของชุด #{batch_id} ({len(serials)} ตัว)")
        dlg.resize(380, 480)
        text = QPlainTextEdit("\n".join(serials))
        text.setReadOnly(True)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText("\n".join(serials)))
        bb.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addWidget(text)
        lay.addWidget(bb)
        dlg.exec()


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = Path(config_path)
        self.app = hl.AppConfig.load(self.config_path)
        self.store = Store(self.app.abspath(self.app.db_file))
        self.setWindowTitle("han-laser  ·  Serial generator for Han's Laser Marking")
        self.resize(1100, 680)

        self.gen_tab = GenerateTab(self)
        self.hist_tab = HistoryTab(self)
        self.settings_tab = SettingsTab(self)
        self.lock_page = LockPage()
        self.settings_stack = QStackedWidget()         # 0 = ล็อก, 1 = Settings
        self.settings_stack.addWidget(self.lock_page)
        self.settings_stack.addWidget(self.settings_tab)
        tabs = QTabWidget()
        tabs.addTab(self.gen_tab, "Generate")
        tabs.addTab(self.hist_tab, "History")
        tabs.addTab(self.settings_stack, "Settings (ล็อก)")
        tabs.currentChanged.connect(self._tab_changed)
        self.tabs = tabs
        self.setCentralWidget(tabs)

        self.gen_tab.generated.connect(self.hist_tab.refresh)
        self.settings_tab.saved.connect(self.config_saved)
        self.settings_tab.change_password_requested.connect(self.change_password)
        self.lock_page.unlock_requested.connect(self.unlock)

        self.mode_lbl = QLabel()
        self.lock_btn = QPushButton("ออกจาก Engineer mode")
        self.lock_btn.clicked.connect(self.lock)
        self.statusBar().addPermanentWidget(self.mode_lbl)
        self.statusBar().addPermanentWidget(self.lock_btn)
        self.statusBar().showMessage(f"config: {self.config_path}   db: {self.store.path}")
        self.reload_all()
        self.lock()

    def reload_all(self) -> None:
        self.gen_tab.reload()
        self.hist_tab.reload()
        self.settings_tab.reload()

    # ------------------------------------------------------------ engineer mode
    @property
    def engineer(self) -> bool:
        return self.settings_stack.currentIndex() == 1

    def lock(self) -> None:
        self.settings_tab.reload()                       # ทิ้งการแก้ที่ยังไม่บันทึก
        self.settings_stack.setCurrentIndex(0)
        self.lock_page.set_has_password(bool(self.app.engineer_password))
        self.tabs.setTabText(2, "Settings (ล็อก)")
        self.mode_lbl.setText("Operator")
        self.lock_btn.hide()

    def unlock(self) -> bool:
        if not self.app.engineer_password:
            dlg = SetPasswordDialog(self, "")
            if not dlg.exec():
                return False
            if not self._store_password(dlg.new_hash):
                return False
        elif not UnlockDialog(self, self.app.engineer_password).exec():
            return False
        self.settings_tab.reload()
        self.settings_stack.setCurrentIndex(1)
        self.tabs.setTabText(2, "Settings (Engineer)")
        self.mode_lbl.setText("<b style='color:#b45309'>Engineer mode</b>")
        self.lock_btn.show()
        return True

    def change_password(self) -> None:
        dlg = SetPasswordDialog(self, self.app.engineer_password)
        if dlg.exec() and self._store_password(dlg.new_hash):
            QMessageBox.information(self, "Engineer mode", "เปลี่ยนรหัสผ่านแล้ว")

    def _store_password(self, new_hash: str) -> bool:
        old = self.app.engineer_password
        self.app.engineer_password = new_hash
        try:
            self.app.save()
        except (ValueError, OSError) as e:
            self.app.engineer_password = old
            error(self, f"บันทึกรหัสผ่านไม่ได้\n\n{e}")
            return False
        if self.settings_tab.work is not None:
            self.settings_tab.work.engineer_password = new_hash
        return True

    def _tab_changed(self, idx: int) -> None:
        # เลขอาจเปลี่ยนตามเวลา (ข้ามวัน/เดือน) อัปเดตทุกครั้งที่กลับมาหน้า Generate
        if self.tabs.widget(idx) is self.gen_tab:
            self.gen_tab.update_preview()

    def config_saved(self, new_app: hl.AppConfig) -> None:
        old_db = self.app.abspath(self.app.db_file)
        self.app = new_app
        if self.app.abspath(self.app.db_file) != old_db:
            self.store.close()
            self.store = Store(self.app.abspath(self.app.db_file))
        self.gen_tab.reload()
        self.hist_tab.reload()
        self.statusBar().showMessage(f"บันทึก config แล้ว {datetime.now():%H:%M:%S}", 5000)

    def closeEvent(self, e):
        self.store.close()
        super().closeEvent(e)
