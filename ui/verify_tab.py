"""หน้า Verify: สแกน serial หลังมาร์ก (เครื่องสแกน USB หรือกล้อง Dino-Lite) ตรวจกับ DB
แล้ว handshake + log ไป FITS และเก็บประวัติ"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import han_laser as hl
from ui.camera import PREVIEW_WIDTH, CameraWorker, CodeGate
from ui.common import error

PLACEHOLDER = "— เลือก —"
GREEN, RED, GREY, BLUE, ORANGE = "#15803d", "#b91c1c", "#6b7280", "#1d4ed8", "#c2410c"
REASON_TH = {
    "": "", "NOT_FOUND": "ไม่พบในระบบ", "WRONG_WORKORDER": "ผิด Workorder", "DUPLICATE": "ซ้ำ",
    "TEST_SERIAL": "SN _test (Operator)", "FITS_HANDSHAKE": "FITS handshake ไม่ผ่าน",
    "FITS_LOG": "FITS log ไม่ผ่าน", "FITS_ERROR": "ติดต่อ FITS ไม่ได้",
}
MODE_OPERATOR, MODE_ENGINEER = 0, 1


def big_font(size: int, bold: bool = True) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    return f


class _JobSignals(QObject):
    done = Signal(int, object)      # verification id, FitsOutcome


class FitsJob(QRunnable):
    """ส่ง FITS ใน thread แยก (UI ไม่ค้างระหว่างรอ) ไม่แตะ DB"""

    def __init__(self, vid, client, fs, serial, names, values, skip_handshake):
        super().__init__()
        self.vid, self.client, self.fs = vid, client, fs
        self.serial, self.names, self.values, self.skip = serial, names, values, skip_handshake
        self.signals = _JobSignals()

    def run(self):
        out = hl.fits_send(self.client, self.fs, self.serial, self.names, self.values, self.skip)
        self.signals.done.emit(self.vid, out)


class VerifyTab(QWidget):
    verified = Signal()
    COLS = ["เวลา", "Serial", "ผล", "สาเหตุ", "FITS", "iQR", "EN", "Shift", "Workorder"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.session_pass = self.session_fail = 0
        self.busy = False
        self.last_fail_vid: int | None = None   # รายการล่าสุดที่ FAIL เพราะ FITS (ปุ่มส่งซ้ำ)
        self._jobs = []                         # กัน signals ถูกเก็บกวาดก่อนเวลา
        self.pool = QThreadPool.globalInstance()
        self.worker: CameraWorker | None = None   # thread กล้อง (เฉพาะโหมดกล้อง)
        self._cam_key = None
        self.gate = CodeGate()
        self.pattern = None                     # regex เลือก serial จาก code ที่กล้องอ่านได้

        # ---- โหมด
        self.mode = QComboBox()
        self.mode.addItem("Operator", MODE_OPERATOR)
        self.mode.addItem("Engineer (TEST)", MODE_ENGINEER)
        self.mode.setMinimumHeight(32)
        self.mode.setFont(big_font(12, False))
        self.banner = QLabel("ENGINEER TEST MODE: SN จะเติม _test ให้อัตโนมัติ และส่งไป FITS TEST endpoint")
        self.banner.setStyleSheet(f"background: {ORANGE}; color: white; padding: 6px; border-radius: 6px;")
        self.banner.setFont(big_font(11))
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.hide()

        # ---- เลือก EN / Shift / Workorder / iQR
        self.en = QComboBox()
        self.shift = QComboBox()
        self.workorder = QComboBox()
        self.iqr = QComboBox()
        for c in (self.en, self.shift, self.workorder, self.iqr):
            c.setMinimumWidth(160)
            c.setMinimumHeight(32)
            c.setFont(big_font(12, False))
        sel = QGridLayout()
        for i, (label, w) in enumerate((("EN", self.en), ("Shift", self.shift),
                                        ("Workorder", self.workorder), ("iQR code", self.iqr))):
            lbl = QLabel(label)
            lbl.setFont(big_font(12))
            sel.addWidget(lbl, i // 2, (i % 2) * 2)
            sel.addWidget(w, i // 2, (i % 2) * 2 + 1)
        mlbl = QLabel("โหมด")
        mlbl.setFont(big_font(12))
        sel.addWidget(mlbl, 2, 0)
        sel.addWidget(self.mode, 2, 1)
        sel.setColumnStretch(1, 1)
        sel.setColumnStretch(3, 1)

        # ---- ช่องสแกน
        self.scan = QLineEdit()
        self.scan.setFont(big_font(20))
        self.scan.setMinimumHeight(56)
        self.scan.setAlignment(Qt.AlignCenter)
        self.scan_hint = QLabel()
        self.scan_hint.setStyleSheet(f"color: {GREY};")
        self.scan_hint.setAlignment(Qt.AlignCenter)
        self.scan_hint.setWordWrap(True)

        # ---- รับค่าจาก: เครื่องสแกน USB หรือกล้อง Dino-Lite (สลับได้ตลอด)
        self.src_usb = QRadioButton("เครื่องสแกน USB")
        self.src_cam = QRadioButton("กล้อง Dino-Lite (อ่านต่อเนื่อง)")
        self.src_group = QButtonGroup(self)
        src_row = QHBoxLayout()
        src_lbl = QLabel("รับค่าจาก")
        src_lbl.setFont(big_font(12))
        src_row.addWidget(src_lbl)
        for b in (self.src_usb, self.src_cam):
            b.setFont(big_font(12, False))
            b.setFocusPolicy(Qt.NoFocus)                   # ไม่แย่ง focus จากช่องสแกน
            self.src_group.addButton(b)
            src_row.addWidget(b)
        src_row.addStretch(1)
        self.src_usb.setChecked(True)

        # ---- ภาพจากกล้อง
        self.cam_view = QLabel("กล้องปิดอยู่")
        self.cam_view.setFixedSize(PREVIEW_WIDTH, PREVIEW_WIDTH * 4 // 5)
        self.cam_view.setAlignment(Qt.AlignCenter)
        self.cam_view.setStyleSheet("background: #111827; color: #d1d5db; border-radius: 6px;")
        self.cam_read = QLabel()
        self.cam_read.setFont(big_font(12))
        self.cam_read.setAlignment(Qt.AlignCenter)
        self.cam_read.setWordWrap(True)
        self.cam_status = QLabel()
        self.cam_status.setWordWrap(True)
        self.cam_status.setMaximumWidth(PREVIEW_WIDTH)
        self.cam_status.setStyleSheet(f"color: {GREY};")
        self.cam_retry = QPushButton("เชื่อมต่อกล้องใหม่")
        self.cam_retry.setFocusPolicy(Qt.NoFocus)
        self.cam_retry.hide()
        self.cam_box = QWidget()
        cl = QVBoxLayout(self.cam_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.cam_view)
        cl.addWidget(self.cam_read)
        cl.addWidget(self.cam_status)
        cl.addWidget(self.cam_retry, 0, Qt.AlignHCenter)
        cl.addStretch(1)
        self.cam_box.hide()

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
        self.retry_btn = QPushButton("ส่ง FITS ซ้ำ")
        self.retry_btn.setMinimumHeight(40)
        self.retry_btn.setFont(big_font(12))
        self.retry_btn.setStyleSheet("QPushButton { background: white; color: #b91c1c; border-radius: 6px;"
                                     " padding: 4px 24px; }")
        self.retry_btn.hide()
        rl = QVBoxLayout(self.result_box)
        for w in (self.result_word, self.result_serial, self.result_msg):
            rl.addWidget(w)
        rl.addWidget(self.retry_btn, 0, Qt.AlignHCenter)

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
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)              # ไม่แย่ง focus จากช่องสแกน
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        hint = QLabel("ประวัติการ verify ล่าสุด (Workorder ที่เลือก) · ดับเบิลคลิกแถวที่ FAIL เพราะ FITS เพื่อส่งซ้ำ")

        left = QVBoxLayout()
        left.addLayout(sel)
        left.addSpacing(6)
        left.addLayout(src_row)
        self.scan_lbl = QLabel("Serial (สแกน code บนชิ้นงาน)")
        self.scan_lbl.setFont(big_font(12))
        left.addWidget(self.scan_lbl)
        left.addWidget(self.scan)
        left.addWidget(self.scan_hint)
        left.addWidget(self.result_box)
        left.addStretch(1)
        top = QHBoxLayout()
        top.addLayout(left, 1)
        top.addWidget(self.cam_box)

        lay = QVBoxLayout(self)
        lay.addWidget(self.banner)
        lay.addLayout(top)
        lay.addLayout(stats)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)

        for c in (self.en, self.shift, self.workorder, self.iqr):
            c.currentIndexChanged.connect(self._selection_changed)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.src_cam.toggled.connect(self._source_changed)
        self.cam_retry.clicked.connect(self.start_camera)
        self.scan.returnPressed.connect(self.do_verify)
        self.retry_btn.clicked.connect(lambda: self.retry(self.last_fail_vid))
        self.table.cellDoubleClicked.connect(self._row_double_clicked)
        self._show_idle()

    # ------------------------------------------------------------ state
    def reload(self) -> None:
        app = self.win.app
        for combo, items in ((self.en, app.operators), (self.shift, app.shifts),
                             (self.workorder, app.workorders), (self.iqr, app.iqr_codes)):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(PLACEHOLDER, None)
            for it in items:
                combo.addItem(it, it)
            idx = combo.findData(cur) if cur is not None else -1
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)
        self.pattern = hl.serial_pattern(app)
        for b in (self.src_usb, self.src_cam):
            b.blockSignals(True)
        (self.src_cam if app.input_mode == "camera" else self.src_usb).setChecked(True)
        for b in (self.src_usb, self.src_cam):
            b.blockSignals(False)
        c = app.camera
        same_cam = self.worker is not None and self._cam_key == (c.index, c.device, c.width, c.height)
        if same_cam:
            self.worker.pattern = self.pattern
        self._apply_source(start=not same_cam)

    @property
    def test_mode(self) -> bool:
        return self.mode.currentData() == MODE_ENGINEER

    def set_operator_mode(self) -> None:
        """เรียกตอนออกจาก Engineer mode"""
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(MODE_OPERATOR)
        self.mode.blockSignals(False)
        self._apply_mode()

    def _mode_changed(self) -> None:
        if self.test_mode and not self.win.engineer and not self.win.unlock():
            self.set_operator_mode()          # ใส่รหัสไม่ผ่าน กลับเป็น Operator
            return
        self._apply_mode()

    def _apply_mode(self) -> None:
        self.banner.setVisible(self.test_mode)
        self._selection_changed()

    def selection(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.en.currentData(), self.shift.currentData(), self.workorder.currentData(),
                self.iqr.currentData())

    def ready(self) -> bool:
        return all(self.selection())

    def _selection_changed(self) -> None:
        ok = self.ready() and not self.busy
        self.scan.setEnabled(ok)
        if self.busy:
            self.scan.setPlaceholderText("กำลังส่ง FITS…")
            if self.camera_mode:
                self.scan_hint.setText("กำลังส่ง FITS… ชิ้นถัดไปจะตรวจเมื่อส่งเสร็จ")
        elif ok:
            self.scan.setPlaceholderText("สแกน QR code ที่นี่" + ("  (จะเติม _test)" if self.test_mode else ""))
            fits = "แล้ว handshake + log ไป FITS" if self.win.app.fits.enabled else "(ปิดการส่ง FITS อยู่)"
            if self.camera_mode:
                self.scan_hint.setText(f"วางชิ้นงานใต้กล้อง อ่านได้แล้วระบบตรวจทันที {fits}"
                                       + ("  (จะเติม _test)" if self.test_mode else "")
                                       + "\nชิ้นเดิมจะไม่ตรวจซ้ำจนกว่าจะเอาออกจากกล้อง")
            else:
                self.scan_hint.setText(f"สแกนแล้วระบบตรวจทันที {fits}")
            self.focus_scan()
        else:
            missing = [n for n, v in zip(("EN", "Shift", "Workorder", "iQR code"), self.selection()) if not v]
            self.scan.setPlaceholderText("เลือก " + ", ".join(missing) + " ก่อน")
            app = self.win.app
            if not (app.operators and app.workorders and app.iqr_codes):
                self.scan_hint.setText("ยังไม่มีรายการ EN / Workorder / iQR code ให้ Engineer เพิ่มในหน้า Settings")
            else:
                self.scan_hint.setText("")
        self.refresh()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.mode.setEnabled(not busy)
        self.retry_btn.setEnabled(not busy)
        self._selection_changed()

    def focus_scan(self) -> None:
        if self.scan.isEnabled():
            QTimer.singleShot(0, self.scan.setFocus)

    # ------------------------------------------------------------ camera
    @property
    def camera_mode(self) -> bool:
        return self.src_cam.isChecked()

    def _source_changed(self, _checked: bool = False) -> None:
        mode = "camera" if self.camera_mode else "usb"
        app = self.win.app
        if app.input_mode != mode:          # จำไว้ใน config เปิดโปรแกรมครั้งหน้าใช้แบบเดิม
            app.input_mode = mode
            try:
                app.save()
            except (ValueError, OSError):
                pass                        # บันทึกไม่ได้ก็ยังใช้ได้รอบนี้
            work = getattr(getattr(self.win, "settings_tab", None), "work", None)
            if work is not None:            # กันหน้า Settings เอาค่าเก่าไปเขียนทับ
                work.input_mode = mode
        self._apply_source()

    def _apply_source(self, start: bool = True) -> None:
        cam = self.camera_mode
        self.scan.setVisible(not cam)
        self.cam_box.setVisible(cam)
        self.scan_lbl.setText("Serial (อ่าน DataMatrix จากกล้องอัตโนมัติ)" if cam else "Serial (สแกน code บนชิ้นงาน)")
        if not cam:
            self.stop_camera()
        elif start:
            self.start_camera()
        self._selection_changed()

    def start_camera(self) -> None:
        self.stop_camera()
        c = self.win.app.camera
        self._cam_key = (c.index, c.device, c.width, c.height)
        self.gate.reset()
        w = CameraWorker(c.index, c.width, c.height, self.pattern, c.device, c.device_name)
        w.opened.connect(self._cam_opened)
        w.failed.connect(self._cam_failed)
        w.codes.connect(self._on_codes)
        w.frame.connect(self._on_frame)
        self.worker = w
        self.cam_retry.hide()
        self.cam_view.setText("กำลังเปิดกล้อง…")
        self.cam_read.setText("")
        self.cam_status.setStyleSheet(f"color: {GREY};")
        self.cam_status.setText("กล้อง: " + (c.device_name or ("หา Dino-Lite อัตโนมัติ" if c.index == "auto"
                                                               else f"index {c.index}")))
        w.start()

    def stop_camera(self) -> None:
        w, self.worker = self.worker, None
        if w is not None:
            w.requestInterruption()
            w.wait(3000)
        self.cam_view.clear()
        self.cam_view.setText("กล้องปิดอยู่")
        self.cam_read.setText("")

    def _stale(self) -> bool:
        """signal จาก thread กล้องตัวเก่าที่หยุดไปแล้ว (มาถึงช้า) ให้ทิ้ง"""
        s = self.sender()
        return s is not None and s is not self.worker

    def _cam_opened(self, desc: str) -> None:
        if not self._stale():
            self.cam_status.setText(f"กล้อง: {desc}")

    def _cam_failed(self, msg: str) -> None:
        if self._stale():
            return
        self.worker = None                  # thread จบไปแล้ว
        self.cam_view.clear()
        self.cam_view.setText("กล้องไม่พร้อม")
        self.cam_read.setText("")
        self.cam_status.setStyleSheet(f"color: {RED};")
        self.cam_status.setText(msg)
        self.cam_retry.show()

    def _on_frame(self, img) -> None:
        if not self._stale():
            self.cam_view.setPixmap(QPixmap.fromImage(img))

    def _on_codes(self, codes: list) -> None:
        if self._stale() or not self.camera_mode:
            return
        serial = hl.pick_serial(self.pattern, codes)
        if serial:
            self.cam_read.setStyleSheet(f"color: {GREEN};")
            self.cam_read.setText(f"อ่านได้: {serial}")
        elif codes:
            self.cam_read.setStyleSheet(f"color: {ORANGE};")
            self.cam_read.setText("พบ code แต่ไม่ใช่ serial: " + ", ".join(codes))
        else:
            self.cam_read.setStyleSheet(f"color: {GREY};")
            self.cam_read.setText("วางชิ้นงานใต้กล้อง")
        got = self.gate.feed(serial, self.ready() and not self.busy)
        if got:
            self.do_verify(got)

    # ------------------------------------------------------------ result box
    def _paint(self, color: str, word: str, serial: str, msg: str, retry: bool = False) -> None:
        self.result_box.setStyleSheet(f"QFrame {{ background: {color}; border-radius: 10px; }}")
        fg = GREY if color == "#f3f4f6" else "white"
        for w in (self.result_word, self.result_serial, self.result_msg):
            w.setStyleSheet(f"color: {fg};")
        self.result_word.setText(word)
        self.result_serial.setText(serial)
        self.result_msg.setText(msg)
        self.retry_btn.setVisible(retry)

    def _show_idle(self) -> None:
        self._paint("#f3f4f6", "READY", "", "")

    def _show_final(self, ok: bool, serial: str, msg: str, test: bool, retry: bool = False) -> None:
        word = ("PASS" if ok else "FAIL") + (" (TEST)" if test else "")
        self._paint(GREEN if ok else RED, word, serial, msg, retry)
        if ok:
            self.session_pass += 1
        else:
            self.session_fail += 1
            QApplication.beep()

    # ------------------------------------------------------------ verify + FITS
    def do_verify(self, raw: str | None = None) -> None:
        """raw = ค่าจากกล้อง; None = อ่านจากช่องสแกน (เครื่องสแกน USB)"""
        if raw is None:
            raw = self.scan.text()
            self.scan.clear()
        if self.busy or not self.ready() or not raw.strip():
            return self.focus_scan()
        en, shift, wo, iqr = self.selection()
        app, test = self.win.app, self.test_mode
        client = None
        if app.fits.enabled:
            try:
                client = self.win.fits_factory(test)
            except hl.FitsSetupError as e:     # ตั้งค่าไม่ครบ ยังไม่บันทึกอะไร
                self._show_final(False, hl.normalize_code(raw), str(e), test)
                return self.focus_scan()
        try:
            r = hl.verify(self.win.store, raw, en, shift, wo, iqr=iqr, test=test, pending=client is not None)
        except (ValueError, OSError) as e:
            error(self, f"บันทึกผลไม่ได้\n\n{e}")
            return self.focus_scan()
        if not r.pending:
            self._show_final(r.ok, r.serial, r.message, r.test)
            self._after()
            return
        self._start_fits(r.id, client, skip_handshake=False)

    def _start_fits(self, vid: int, client, skip_handshake: bool) -> None:
        store, app = self.win.store, self.win.app
        row = store.verification(vid)
        try:
            names, values = hl.fits_log_values(app, hl.fits_context(row))
        except hl.FitsSetupError as e:
            out = hl.FitsOutcome(False, row["fits_handshake"], "", str(e), "FITS_ERROR")
            return self._fits_done(vid, out)
        self._paint(BLUE, "กำลังส่ง FITS…", row["serial"],
                    "ตรวจในเครื่องผ่านแล้ว รอ " + ("log" if skip_handshake else "handshake + log"))
        self._set_busy(True)
        job = FitsJob(vid, client, app.fits, row["serial"], names, values, skip_handshake)
        job.signals.done.connect(self._fits_done)
        self._jobs.append(job)
        self.pool.start(job)

    def _fits_done(self, vid: int, out: hl.FitsOutcome) -> None:
        self._jobs = [j for j in self._jobs if j.vid != vid]
        try:
            hl.finish_fits(self.win.store, vid, out)
        except (ValueError, OSError) as e:
            error(self, f"บันทึกผล FITS ไม่ได้\n\n{e}")
        row = self.win.store.verification(vid)
        self.last_fail_vid = None if out.ok else vid
        self._set_busy(False)
        self._show_final(out.ok, row["serial"], out.message, bool(row["test"]), retry=not out.ok)
        self._after()

    def retry(self, vid: int | None) -> None:
        if vid is None or self.busy:
            return
        try:
            row, skip = hl.retry_check(self.win.store, vid)
            client = self.win.fits_factory(bool(row["test"]))
        except ValueError as e:              # รวม FitsSetupError
            error(self, str(e))
            return self.focus_scan()
        self._start_fits(vid, client, skip_handshake=skip)

    def _row_double_clicked(self, r: int, _c: int) -> None:
        item = self.table.item(r, 0)
        if item is not None:
            self.retry(item.data(Qt.UserRole))

    def _after(self) -> None:
        self.refresh()
        self.verified.emit()
        self.focus_scan()

    # ------------------------------------------------------------ table
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
            fits = ""
            if row["fits_handshake"] or row["fits_log"]:
                fits = f"HS {row['fits_handshake'] or '-'} · LOG {row['fits_log'] or '-'}"
            result = row["result"] + (" TEST" if row["test"] else "")
            vals = [row["scanned_at"].replace("T", " "), row["serial"], result,
                    REASON_TH.get(row["reason"], row["reason"]), fits, row["iqr"], row["en"], row["shift"],
                    row["workorder"]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.UserRole, row["id"])
                if c == 2:
                    item.setForeground(Qt.white)
                    bg = {"PASS": Qt.darkGreen, "PENDING": QColor(BLUE)}.get(row["result"], Qt.darkRed)
                    item.setBackground(bg)
                if c == 4 and row["fits_message"]:
                    item.setToolTip(row["fits_message"])
                self.table.setItem(r, c, item)
