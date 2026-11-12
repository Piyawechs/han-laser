import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import han_laser as hl  # noqa: E402
from store import Store  # noqa: E402


def product(pid, prefix, **kw):
    d = {"name": pid.title(), "prefix": prefix, "template": f"{pid}.hs",
         "serial_txt": f"out/serial_{pid}.txt", "seq_max": 20}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.write_cfg({"last_product": "ceramic_box",
                        "products": {"ceramic_box": product("ceramic_box", "CB"),
                                     "lid": product("lid", "LD")}})
        self.day1 = datetime(2026, 11, 10, 9, 0, 0)

    def write_cfg(self, raw):
        (self.dir / "config.json").write_text(json.dumps(raw), encoding="utf-8")
        self.app = hl.AppConfig.load(self.dir / "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def txt(self, pid):
        return (self.dir / f"out/serial_{pid}.txt").read_bytes().decode()

    def gen(self, count, pid=None, lot="", now=None):
        return hl.generate(self.app, pid, count, lot, now=now or self.day1)


class GenerateTest(Base):
    def test_one_serial_per_line_crlf(self):
        b = self.gen(3, lot="LOT1")
        self.assertEqual(b.serials, ["CB26110001", "CB26110002", "CB26110003"])
        self.assertEqual(self.txt("ceramic_box"), "CB26110001\r\nCB26110002\r\nCB26110003\r\n")

    def test_products_have_separate_sequence_and_file(self):
        self.gen(2, "ceramic_box")
        b = self.gen(2, "lid")
        self.assertEqual(b.serials, ["LD26110001", "LD26110002"])
        self.assertEqual(self.txt("ceramic_box"), "CB26110001\r\nCB26110002\r\n")
        self.assertEqual(self.gen(1, "ceramic_box").serials, ["CB26110003"])

    def test_default_product_is_last_product(self):
        self.assertTrue(self.gen(1).serials[0].startswith("CB"))

    def test_continues_and_archives_previous(self):
        self.gen(2)
        b = self.gen(2, now=self.day1.replace(hour=10))
        self.assertEqual(b.serials, ["CB26110003", "CB26110004"])
        self.assertEqual(len(list((self.dir / "data/archive").iterdir())), 1)

    def test_monthly(self):
        self.gen(2)
        self.assertEqual(self.gen(1, now=datetime(2026, 11, 30, 23)).serials, ["CB26110003"])
        self.assertEqual(self.gen(1, now=datetime(2026, 12, 1, 8)).serials, ["CB26120001"])

    def test_daily_reset(self):
        p = self.app.products["ceramic_box"]
        p.seq_reset, p.serial_format = "daily", "{prefix}{date:%y%m%d}{seq:04d}"
        self.gen(2)
        self.assertEqual(self.gen(1, now=datetime(2026, 11, 11, 8)).serials, ["CB2611110001"])

    def test_mismatched_reset_caught_as_duplicate(self):
        self.app.products["ceramic_box"].serial_format = "{prefix}{seq:04d}"
        self.gen(2)
        with self.assertRaises(ValueError):
            self.gen(1, now=datetime(2026, 12, 1, 8))

    def test_seq_max_rejected_and_nothing_written(self):
        with self.assertRaises(ValueError):
            self.gen(21)
        self.assertFalse((self.dir / "out/serial_ceramic_box.txt").exists())
        with hl.open_store(self.app) as s:
            self.assertEqual(s.list_batches(), [])

    def test_txt_write_failure_rolls_back(self):
        with mock.patch.object(hl, "atomic_write_text", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.gen(3)
        with hl.open_store(self.app) as s:
            self.assertEqual(s.list_batches(), [])
            self.assertIsNone(s.last_seq("ceramic_box", "2026-11"))
        self.assertEqual(self.gen(1).serials, ["CB26110001"])

    def test_missing_txt_dir_outside_project_rejected(self):
        self.app.products["lid"].serial_txt = str(self.dir.parent / "no_such_dir_xyz" / "s.txt")
        with self.assertRaises(ValueError) as cm:
            self.gen(1, "lid")
        self.assertIn("Settings", str(cm.exception))
        with hl.open_store(self.app) as s:
            self.assertEqual(s.list_batches(), [])

    def test_txt_dir_inside_project_created(self):
        self.app.products["lid"].serial_txt = "serial/deep/s.txt"
        self.gen(1, "lid")
        self.assertTrue((self.dir / "serial/deep/s.txt").exists())

    def test_preview_does_not_write(self):
        self.assertEqual(hl.preview(self.app, "lid", 2, now=self.day1), ["LD26110001", "LD26110002"])
        self.assertEqual(self.gen(1, "lid").serials, ["LD26110001"])

    def test_history_in_db(self):
        b = self.gen(2, "lid", lot="LOT9")
        with hl.open_store(self.app) as s:
            rows = s.list_batches()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["product"], rows[0]["lot"], rows[0]["first_serial"],
                              rows[0]["last_serial"], rows[0]["count"]),
                             ("lid", "LOT9", "LD26110001", "LD26110002", 2))
            self.assertEqual(s.serials_of(b.id), ["LD26110001", "LD26110002"])
            self.assertEqual(len(s.list_batches(lot_like="OT9")), 1)
            self.assertEqual(len(s.list_batches(product="ceramic_box")), 0)


class LaunchTest(Base):
    def setUp(self):
        super().setUp()
        (self.dir / "ceramic_box.hs").write_text("x")
        self.exe = self.dir / "HANS" / "HLM.exe"
        self.exe.parent.mkdir()
        self.exe.write_text("x")

    def test_uses_associated_exe_with_exe_folder_as_cwd(self):
        with mock.patch.object(hl, "associated_exe", return_value=str(self.exe)), \
             mock.patch.object(hl, "is_running", return_value=False), \
             mock.patch.object(hl.subprocess, "Popen") as popen:
            hl.launch(self.app, "ceramic_box")
        args, kw = popen.call_args
        self.assertEqual(args[0], [str(self.exe), str((self.dir / "ceramic_box.hs").resolve())])
        self.assertEqual(kw["cwd"], str(self.exe.parent))

    def test_refuses_when_already_running(self):
        self.app.products["ceramic_box"].marking_exe = str(self.exe)
        with mock.patch.object(hl, "is_running", return_value=True), \
             mock.patch.object(hl.subprocess, "Popen") as popen:
            with self.assertRaises(OSError):
                hl.launch(self.app, "ceramic_box")
        popen.assert_not_called()

    def test_no_exe_found(self):
        with mock.patch.object(hl, "associated_exe", return_value=None):
            with self.assertRaises(OSError):
                hl.launch(self.app, "ceramic_box")


class ConfigTest(Base):
    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            self.write_cfg({"products": {"x": product("x", "X", typo=1)}})

    def test_needs_seq_in_format(self):
        with self.assertRaises(ValueError):
            self.write_cfg({"products": {"x": product("x", "X", serial_format="{prefix}")}})

    def test_bad_format(self):
        with self.assertRaises(ValueError):
            self.write_cfg({"products": {"x": product("x", "X", serial_format="{seq:04d}{nope}")}})

    def test_same_txt_rejected(self):
        with self.assertRaises(ValueError):
            self.write_cfg({"products": {"a": product("a", "A", serial_txt="s.txt"),
                                         "b": product("b", "B", serial_txt="s.txt")}})

    def test_lists_must_be_strings(self):
        with self.assertRaises(ValueError):
            self.write_cfg({"workorders": ["ok", ""], "products": {"a": product("a", "A")}})

    def test_bad_encoding(self):
        with self.assertRaises(ValueError):
            self.write_cfg({"txt_encoding": "nope", "products": {"a": product("a", "A")}})

    def test_save_roundtrip_keeps_relative_paths(self):
        self.app.products["lid"].prefix = "LID"
        self.app.save()
        raw = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["products"]["lid"]["serial_txt"], "out/serial_lid.txt")
        self.assertNotIn("id", raw["products"]["lid"])
        again = hl.AppConfig.load(self.dir / "config.json")
        self.assertEqual(again.products["lid"].prefix, "LID")
        self.assertEqual(again.to_dict(), self.app.to_dict())

    def test_example_config_is_valid(self):
        shutil.copy(ROOT / "config.example.json", self.dir / "ex.json")
        app = hl.AppConfig.load(self.dir / "ex.json")
        self.assertEqual(set(app.products), {"ceramic_box", "lid"})
        self.assertEqual(hl.preview(app, "ceramic_box", 1, now=self.day1), ["CB26110001"])


class PasswordTest(Base):
    def test_hash_and_verify(self):
        h = hl.hash_password("1234")
        self.assertNotIn("1234", h)
        self.assertTrue(hl.verify_password("1234", h))
        self.assertFalse(hl.verify_password("12345", h))
        self.assertFalse(hl.verify_password("1234", ""))
        self.assertFalse(hl.verify_password("1234", "garbage"))
        self.assertNotEqual(h, hl.hash_password("1234"))  # salt ต่างกัน

    def test_saved_in_config(self):
        self.app.engineer_password = hl.hash_password("abcd")
        self.app.save()
        again = hl.AppConfig.load(self.dir / "config.json")
        self.assertTrue(hl.verify_password("abcd", again.engineer_password))


class VerifyTest(Base):
    def setUp(self):
        super().setUp()
        self.store = hl.open_store(self.app)
        hl.generate(self.app, "ceramic_box", 3, "WO1", now=self.day1, store=self.store)
        hl.generate(self.app, "lid", 2, "WO2", now=self.day1, store=self.store)

    def tearDown(self):
        self.store.close()
        super().tearDown()

    def v(self, code, wo="WO1"):
        return hl.verify(self.store, code, "EN01", "A", wo, now=self.day1, iqr="IQR9")

    def test_pass(self):
        r = self.v("CB26110001")
        self.assertTrue(r.ok)
        self.assertEqual((r.serial, r.product, r.reason), ("CB26110001", "ceramic_box", ""))

    def test_scanner_whitespace_and_case(self):
        self.assertTrue(self.v("  cb26110002\r\n").ok)

    def test_not_found(self):
        r = self.v("CB26119999")
        self.assertEqual((r.ok, r.reason), (False, "NOT_FOUND"))

    def test_wrong_workorder(self):
        r = self.v("LD26110001", wo="WO1")
        self.assertEqual((r.ok, r.reason), (False, "WRONG_WORKORDER"))
        self.assertIn("WO2", r.message)

    def test_duplicate_after_pass_only(self):
        self.v("CB26110003", wo="WO2")              # FAIL ไม่นับเป็นซ้ำ
        self.assertTrue(self.v("CB26110003").ok)
        r = self.v("CB26110003")
        self.assertEqual((r.ok, r.reason), (False, "DUPLICATE"))
        self.assertIn("EN01", r.message)

    def test_everything_logged_and_stats(self):
        self.v("CB26110001")
        self.v("CB26110001")
        self.v("XXX")
        rows = self.store.list_verifications("WO1")
        self.assertEqual([r["result"] for r in rows], ["FAIL", "FAIL", "PASS"])
        self.assertEqual(rows[0]["raw_code"], "XXX")
        self.assertEqual(rows[2]["iqr"], "IQR9")
        self.assertEqual(self.store.workorder_stats("WO1"), {"generated": 3, "passed": 1, "failed": 2})

    def test_empty_not_logged(self):
        self.assertEqual(self.v("   ").reason, "EMPTY")
        self.assertEqual(self.store.list_verifications(), [])

    def test_requires_selection(self):
        with self.assertRaises(ValueError):
            hl.verify(self.store, "CB26110001", "", "A", "WO1")


class StoreTest(unittest.TestCase):
    def test_migrates_old_verifications_table(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "old.db"
            c = sqlite3.connect(db)
            c.execute("CREATE TABLE verifications (id INTEGER PRIMARY KEY AUTOINCREMENT, scanned_at TEXT NOT NULL,"
                      " raw_code TEXT NOT NULL, serial TEXT NOT NULL, product TEXT NOT NULL DEFAULT '',"
                      " en TEXT NOT NULL, shift TEXT NOT NULL, workorder TEXT NOT NULL, result TEXT NOT NULL,"
                      " reason TEXT NOT NULL DEFAULT '')")
            c.execute("INSERT INTO verifications (scanned_at, raw_code, serial, en, shift, workorder, result)"
                      " VALUES ('t', 'A', 'A', 'e', 's', 'w', 'PASS')")
            c.commit()
            c.close()
            with Store(db) as s:
                rows = s.list_verifications()
                self.assertEqual((len(rows), rows[0]["iqr"]), (1, ""))
                with s.transaction():
                    s.add_verification("t", "B", "B", "", "e", "s", "w", "PASS", "", iqr="Q1")
                self.assertEqual(s.list_verifications()[0]["iqr"], "Q1")

    def test_primary_key_blocks_duplicates(self):
        with tempfile.TemporaryDirectory() as d, Store(Path(d) / "x.db") as s:
            with s.transaction():
                s.add_batch("p", "", ["A1"], [1], "all", "t", "now")
            with self.assertRaises(Exception):
                with s.transaction():
                    s.add_batch("p", "", ["A2", "A1"], [2, 1], "all", "t", "now")
            self.assertEqual(len(s.list_batches()), 1)
            self.assertEqual(s.existing(["A1", "A2"]), ["A1"])


if __name__ == "__main__":
    unittest.main()
