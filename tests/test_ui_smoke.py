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
        self.assertEqual(v.scan.text(), "")              # เคลียร์รอสแกนต่อ
        self.assertIn("ผ่านแล้ว <b>2</b> / generate 3", v.stat_wo.text())

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
