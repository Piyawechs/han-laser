"""ทดสอบ UI แบบไม่มีหน้าจอ (QT_QPA_PLATFORM=offscreen) ข้ามถ้าไม่มี PySide6"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # pragma: no cover
    QApplication = None


class FakeFits:
    """แทน fits_client.FitsClient"""

    class R:
        def __init__(self, ok, message):
            self.ok, self.message = ok, message

    def __init__(self, handshake_ok=True, log_ok=True, log_error=False):
        self.handshake_ok, self.log_ok, self.log_error = handshake_ok, log_ok, log_error
        self.calls = []

    def handshake(self, model, operation, serial):
        self.calls.append(("handshake", model, operation, serial))
        return self.R(self.handshake_ok, "OK" if self.handshake_ok else "Wrong route")

    def log(self, model, operation, names, values, fsp=","):
        self.calls.append(("log", model, operation, list(names), list(values)))
        if self.log_error:
            raise OSError("network down")
        return self.R(self.log_ok, "logged")


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class UISmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui.main_window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        raw = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        for pid, p in raw["products"].items():
            p["template"] = f"{pid}.hs"
            p["serial_txt"] = f"out/serial_{pid}.txt"
            p["image"] = str(ROOT / p["image"])
        (d / "config.json").write_text(json.dumps(raw), encoding="utf-8")
        self.dir = d
        self.win = MainWindow(d / "config.json")
        self.patches = [
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
            mock.patch.object(QMessageBox, "information"),
            mock.patch.object(QMessageBox, "critical", side_effect=AssertionError("error dialog")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.win.close()
        self.tmp.cleanup()

    def test_generate_flow(self):
        g = self.win.gen_tab
        self.assertFalse(g.gen_btn.isEnabled())          # ยังไม่กรอก lot
        g.product.setCurrentIndex(g.product.findData("lid"))
        g.lot.setCurrentText("WO-TEST-001")
        g.count.setValue(5)
        self.assertTrue(g.gen_btn.isEnabled())
        self.assertIn("LD", g.range_lbl.text())
        g.gen_btn.click()
        lines = (self.dir / "out/serial_lid.txt").read_text().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith("LD") and lines[0].endswith("0001"))
        self.assertTrue(g.next_lbl.text().endswith("0006"))
        h = self.win.hist_tab
        self.assertEqual(h.table.rowCount(), 1)
        self.assertEqual(h.table.item(0, 2).text(), "WO-TEST-001")
        # จำ product ล่าสุด
        self.assertEqual(json.loads((self.dir / "config.json").read_text())["last_product"], "lid")

    def test_settings_save_roundtrip(self):
        s = self.win.settings_tab
        s.list.setCurrentRow(list(self.win.app.products).index("lid"))
        s.prefix.setText("LID")
        self.assertIn("LID", s.example.text())
        s.save()
        raw = json.loads((self.dir / "config.json").read_text())
        self.assertEqual(raw["products"]["lid"]["prefix"], "LID")
        self.assertEqual(self.win.app.products["lid"].prefix, "LID")
        g = self.win.gen_tab
        g.product.setCurrentIndex(g.product.findData("lid"))
        self.assertTrue(g.next_lbl.text().startswith("LID"))

    def test_settings_locked_by_default_and_unlock(self):
        import han_laser as hl
        from ui import main_window as mw
        w = self.win
        self.assertFalse(w.engineer)
        self.assertEqual(w.settings_stack.currentIndex(), 0)
        # ครั้งแรก: ยังไม่มีรหัส -> ตั้งรหัสใหม่
        def fake_set_exec(dlg):
            dlg.new_hash = hl.hash_password("9999")
            return True
        with mock.patch.object(mw.SetPasswordDialog, "exec", fake_set_exec):
            self.assertTrue(w.unlock())
        self.assertTrue(w.engineer)
        saved = json.loads((self.dir / "config.json").read_text())["engineer_password"]
        self.assertTrue(hl.verify_password("9999", saved))
        w.lock()
        self.assertFalse(w.engineer)
        # ครั้งต่อไป: ใส่รหัสผิด -> เข้าไม่ได้
        with mock.patch.object(mw.UnlockDialog, "exec", return_value=False):
            self.assertFalse(w.unlock())
        self.assertFalse(w.engineer)
        # settings save ต้องไม่ลบรหัส
        with mock.patch.object(mw.UnlockDialog, "exec", return_value=True):
            self.assertTrue(w.unlock())
        w.settings_tab.save()
        saved2 = json.loads((self.dir / "config.json").read_text())["engineer_password"]
        self.assertEqual(saved, saved2)

    def test_unlock_dialog_checks_password(self):
        import han_laser as hl
        from ui.engineer import UnlockDialog
        dlg = UnlockDialog(self.win, hl.hash_password("pass"))
        dlg.pw.setText("wrong")
        dlg._ok()
        self.assertEqual(dlg.result(), 0)
        self.assertIn("ไม่ถูกต้อง", dlg.msg.text())
        dlg.pw.setText("pass")
        dlg._ok()
        self.assertEqual(dlg.result(), 1)

    def _verify_some(self):
        import han_laser as hl
        hl.generate(self.win.app, "ceramic_box", 3, "WO-TEST-001", store=self.win.store)
        v = self.win.verify_tab
        v.reload()
        v.en.setCurrentIndex(v.en.findData("EN001"))
        v.shift.setCurrentIndex(v.shift.findData("A"))
        v.workorder.setCurrentIndex(v.workorder.findData("WO-TEST-001"))
        self.assertFalse(v.scan.isEnabled())              # ยังไม่เลือก iQR
        v.iqr.setCurrentIndex(v.iqr.findData("IQR-TEST-01"))
        serial = hl.preview(self.win.app, "ceramic_box", 1, store=self.win.store)[0]
        first = serial[:-4] + str(int(serial[-4:]) - 3).zfill(4)
        for code in (first, first, "NOPE123"):
            v.scan.setText(code)
            v.do_verify()
        v.scan.setText(serial[:-4] + str(int(serial[-4:]) - 2).zfill(4))
        v.do_verify()
        return v

    def test_verify_tab(self):
        v = self.win.verify_tab
        self.assertIs(self.win.tabs.widget(0), v)
        self.assertFalse(v.scan.isEnabled())             # ยังไม่เลือก EN/Shift/WO
        with mock.patch("ui.verify_tab.QApplication.beep"):
            v = self._verify_some()
        self.assertTrue(v.scan.isEnabled())
        self.assertEqual(v.result_word.text(), "PASS")
        self.assertEqual((v.session_pass, v.session_fail), (2, 2))
        self.assertEqual(v.table.rowCount(), 4)
        self.assertEqual(v.table.item(1, 2).text(), "FAIL")
        self.assertEqual(v.table.item(0, 5).text(), "IQR-TEST-01")
        self.assertEqual(v.scan.text(), "")              # เคลียร์รอสแกนต่อ
        self.assertIn("ผ่านแล้ว <b>2</b> / generate 3", v.stat_wo.text())

    # ---------------- FITS
    def _fits_setup(self, fake):
        import han_laser as hl
        app = self.win.app
        app.fits = hl.FitsSettings(enabled=True, model="M", operation="OP",
                                   parameters=[["SN", "serial"], ["WO", "workorder"], ["PN", "wo_pn"],
                                               ["IQR", "iqr"], ["Result", "result"], ["FC", "failure_code"]])
        app.workorder_pn = {"WO-TEST-001": "PN-1"}
        self.calls = []
        self.win.fits_factory = lambda test: (self.calls.append(("client", test)), fake)[1]
        hl.generate(app, "ceramic_box", 3, "WO-TEST-001", store=self.win.store)
        v = self.win.verify_tab
        v.reload()
        for combo, val in ((v.en, "EN001"), (v.shift, "A"), (v.workorder, "WO-TEST-001"),
                           (v.iqr, "IQR-TEST-01")):
            combo.setCurrentIndex(combo.findData(val))
        self.first = hl.preview(app, "ceramic_box", 1, store=self.win.store)[0][:-4] + "0001"
        return v

    def _scan(self, v, code):
        from PySide6.QtCore import QThreadPool
        v.scan.setText(code)
        v.do_verify()
        QThreadPool.globalInstance().waitForDone(5000)
        for _ in range(5):
            self.qapp.processEvents()

    def test_fits_pass_sends_handshake_then_log(self):
        fake = FakeFits()
        v = self._fits_setup(fake)
        with mock.patch("ui.verify_tab.QApplication.beep"):
            self._scan(v, self.first)
        self.assertEqual(v.result_word.text(), "PASS")
        self.assertEqual([c[0] for c in fake.calls], ["handshake", "log"])
        self.assertEqual(fake.calls[0][1:], ("M", "OP", self.first))
        self.assertEqual(fake.calls[1][3], ["SN", "WO", "PN", "IQR", "Result", "FC"])
        self.assertEqual(fake.calls[1][4], [self.first, "WO-TEST-001", "PN-1", "IQR-TEST-01", "PASS", ""])
        row = self.win.store.list_verifications()[0]
        self.assertEqual((row["result"], row["fits_handshake"], row["fits_log"]), ("PASS", "OK", "OK"))
        self.assertEqual(self.calls, [("client", False)])

    def test_fits_handshake_refused(self):
        fake = FakeFits(handshake_ok=False)
        v = self._fits_setup(fake)
        with mock.patch("ui.verify_tab.QApplication.beep"):
            self._scan(v, self.first)
        self.assertEqual(v.result_word.text(), "FAIL")
        self.assertIn("Handshake", v.result_msg.text())
        self.assertEqual([c[0] for c in fake.calls], ["handshake"])
        self.assertEqual(self.win.store.list_verifications()[0]["reason"], "FITS_HANDSHAKE")

    def test_fits_network_error_then_retry(self):
        fake = FakeFits(log_error=True)
        v = self._fits_setup(fake)
        with mock.patch("ui.verify_tab.QApplication.beep"):
            self._scan(v, self.first)
            self.assertEqual(v.result_word.text(), "FAIL")
            self.assertTrue(v.retry_btn.isVisibleTo(v))
            row = self.win.store.list_verifications()[0]
            self.assertEqual((row["reason"], row["fits_handshake"], row["fits_log"]),
                             ("FITS_ERROR", "OK", "ERROR"))
            fake.log_error = False
            from PySide6.QtCore import QThreadPool
            v.retry_btn.click()
            QThreadPool.globalInstance().waitForDone(5000)
            for _ in range(5):
                self.qapp.processEvents()
        self.assertEqual(v.result_word.text(), "PASS")
        # retry ข้าม handshake (ผ่านแล้ว) ส่งแค่ log
        self.assertEqual([c[0] for c in fake.calls], ["handshake", "log", "log"])
        rows = self.win.store.list_verifications()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], "PASS")

    def test_engineer_mode_adds_test_suffix_and_uses_test_endpoint(self):
        import han_laser as hl
        fake = FakeFits()
        v = self._fits_setup(fake)
        self.win.app.engineer_password = hl.hash_password("1234")
        from ui import main_window as mw
        with mock.patch.object(mw.UnlockDialog, "exec", return_value=True):
            v.mode.setCurrentIndex(1)
        self.assertTrue(v.test_mode)
        self.assertTrue(v.banner.isVisibleTo(v))
        with mock.patch("ui.verify_tab.QApplication.beep"):
            self._scan(v, self.first)
            self._scan(v, self.first)                # test ซ้ำได้
        self.assertEqual(v.result_word.text(), "PASS (TEST)")
        self.assertEqual(fake.calls[0][3], self.first + "_test")
        self.assertEqual(self.calls, [("client", True), ("client", True)])
        rows = self.win.store.list_verifications()
        self.assertTrue(all(r["test"] == 1 for r in rows))
        self.assertEqual(self.win.store.workorder_stats("WO-TEST-001")["passed"], 0)
        # ออกจาก engineer -> กลับ operator และ _test ถูกปฏิเสธ
        self.win.lock()
        self.assertFalse(v.test_mode)
        with mock.patch("ui.verify_tab.QApplication.beep"):
            self._scan(v, self.first + "_test")
        self.assertEqual(self.win.store.list_verifications()[0]["reason"], "TEST_SERIAL")

    def test_engineer_mode_wrong_password_stays_operator(self):
        import han_laser as hl
        self.win.app.engineer_password = hl.hash_password("1234")
        from ui import main_window as mw
        v = self.win.verify_tab
        with mock.patch.object(mw.UnlockDialog, "exec", return_value=False):
            v.mode.setCurrentIndex(1)
        self.assertFalse(v.test_mode)

    # ---------------- camera
    def test_code_gate(self):
        from ui.camera import CodeGate
        g = CodeGate(clear_after=3)
        self.assertEqual(g.feed("A"), "A")
        self.assertIsNone(g.feed("A"))                    # ชิ้นเดิมยังอยู่ใต้กล้อง
        self.assertIsNone(g.feed(None))
        self.assertIsNone(g.feed("A"))                    # หายไปแค่เฟรมเดียว ยังไม่นับว่าเอาออก
        self.assertEqual(g.feed("B"), "B")                # เปลี่ยนชิ้น ส่งทันที
        for _ in range(3):
            g.feed(None)
        self.assertEqual(g.feed("B"), "B")                # เอาออกแล้ววางใหม่ ส่งอีกครั้ง
        self.assertIsNone(g.feed("C", can_accept=False))  # ยังไม่พร้อม ไม่นับว่าส่งแล้ว
        self.assertEqual(g.feed("C"), "C")

    def _camera_tab(self):
        """สลับเป็นโหมดกล้องโดยใช้ worker ปลอม (ไม่ต้องมีกล้องจริง)"""
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtGui import QImage

        class FakeWorker(QObject):
            opened, failed, codes, frame = Signal(str), Signal(str), Signal(list), Signal(QImage)
            instances = []

            def __init__(self, index, width, height, pattern):
                super().__init__()
                self.index, self.pattern, self.running = index, pattern, False
                FakeWorker.instances.append(self)

            def start(self):
                self.running = True

            def requestInterruption(self):
                self.running = False

            def wait(self, _ms):
                return True

        p = mock.patch("ui.verify_tab.CameraWorker", FakeWorker)
        p.start()
        self.addCleanup(p.stop)
        return FakeWorker

    def test_camera_mode_verifies_once_per_piece(self):
        import han_laser as hl
        Fake = self._camera_tab()
        hl.generate(self.win.app, "ceramic_box", 3, "WO-TEST-001", store=self.win.store)
        v = self.win.verify_tab
        v.reload()
        v.src_cam.setChecked(True)
        self.assertTrue(v.camera_mode)
        self.assertEqual(self.win.app.input_mode, "camera")
        saved = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["input_mode"], "camera")       # จำไว้ใช้ครั้งหน้า
        self.assertTrue(v.scan.isHidden() and not v.cam_box.isHidden())
        w = Fake.instances[-1]
        self.assertTrue(w.running)

        first = hl.preview(self.win.app, "ceramic_box", 1, store=self.win.store)[0][:-4] + "0001"
        other = "384008262264500007"
        w.codes.emit([other, first])                         # ยังไม่เลือก EN ฯลฯ: ยังไม่ตรวจ
        self.assertEqual(v.table.rowCount(), 0)
        for combo, val in ((v.en, "EN001"), (v.shift, "A"), (v.workorder, "WO-TEST-001"),
                           (v.iqr, "IQR-TEST-01")):
            combo.setCurrentIndex(combo.findData(val))
        with mock.patch("ui.verify_tab.QApplication.beep"):
            for _ in range(5):
                w.codes.emit([other, first])                 # ชิ้นเดิมค้างใต้กล้อง: ตรวจครั้งเดียว
            self.assertEqual(v.result_word.text(), "PASS")
            self.assertEqual(v.result_serial.text(), first)
            self.assertEqual(v.table.rowCount(), 1)
            w.codes.emit([other])                            # มีแต่ code อื่น: ไม่ตรวจ
            self.assertIn("ไม่ใช่ serial", v.cam_read.text())
            for _ in range(v.gate.clear_after):
                w.codes.emit([])                             # เอาชิ้นออก
            w.codes.emit([first])                            # วางชิ้นเดิมซ้ำ: ตรวจอีกครั้ง = ซ้ำ
            self.assertEqual(v.result_word.text(), "FAIL")
            self.assertEqual(v.table.rowCount(), 2)

        old = w                                              # signal จาก thread เก่าต้องไม่มีผล
        v.src_usb.setChecked(True)
        self.assertFalse(old.running)
        self.assertFalse(v.scan.isHidden())
        old.codes.emit([first[:-4] + "0002"])
        self.assertEqual(v.table.rowCount(), 2)
        self.assertEqual(self.win.app.input_mode, "usb")

    def test_camera_failure_shows_retry(self):
        Fake = self._camera_tab()
        v = self.win.verify_tab
        v.src_cam.setChecked(True)
        Fake.instances[-1].failed.emit("หากล้อง Dino-Lite ไม่เจอ")
        self.assertIsNone(v.worker)
        self.assertFalse(v.cam_retry.isHidden())
        self.assertIn("ไม่เจอ", v.cam_status.text())
        v.cam_retry.click()
        self.assertTrue(Fake.instances[-1].running)
        self.assertTrue(v.cam_retry.isHidden())

    def test_camera_settings_saved(self):
        self.win.unlock = lambda: True
        st = self.win.settings_tab
        st.reload()
        st.cam_index.setCurrentText("1")
        st.cam_regex.setText(r"^CB\d+")
        st.save()
        self.assertEqual((self.win.app.camera.index, self.win.app.camera.serial_regex), ("1", r"^CB\d+"))
        st.cam_regex.setText("(bad")
        with mock.patch("ui.settings_tab.error") as err:
            st.save()
        err.assert_called_once()

    def test_screenshot(self):
        self.win.resize(1100, 680)
        self.win.show()
        self.win.gen_tab.lot.setCurrentText("WO-TEST-001")
        out = os.environ.get("HANLASER_SHOT_DIR")
        if out:
            self.qapp.processEvents()
            self.win.grab().save(str(Path(out) / "generate.png"))
            self._verify_some()
            for i, name in ((0, "verify"), (1, "generate")):
                self.win.tabs.setCurrentIndex(i)
                self.qapp.processEvents()
                self.win.grab().save(str(Path(out) / f"{name}.png"))
            self.win.tabs.setCurrentIndex(3)
            self.qapp.processEvents()
            self.win.grab().save(str(Path(out) / "locked.png"))
            self.win.settings_stack.setCurrentIndex(1)
            for i, name in ((2, "history"), (3, "settings")):
                self.win.tabs.setCurrentIndex(i)
                self.qapp.processEvents()
                self.win.grab().save(str(Path(out) / f"{name}.png"))


if __name__ == "__main__":
    unittest.main()
