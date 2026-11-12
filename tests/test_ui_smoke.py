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
        g.lot.setText("LOT-A")
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
        self.assertEqual(h.table.item(0, 2).text(), "LOT-A")
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

    def test_screenshot(self):
        self.win.resize(1100, 680)
        self.win.show()
        self.win.gen_tab.lot.setText("LOT001")
        out = os.environ.get("HANLASER_SHOT_DIR")
        if out:
            self.qapp.processEvents()
            self.win.grab().save(str(Path(out) / "generate.png"))
            self.win.tabs.setCurrentIndex(2)
            self.qapp.processEvents()
            self.win.grab().save(str(Path(out) / "locked.png"))
            self.win.settings_stack.setCurrentIndex(1)
            for i, name in ((1, "history"), (2, "settings")):
                self.win.tabs.setCurrentIndex(i)
                self.qapp.processEvents()
                self.win.grab().save(str(Path(out) / f"{name}.png"))


if __name__ == "__main__":
    unittest.main()
