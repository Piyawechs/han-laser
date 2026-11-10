import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import han_laser as hl  # noqa: E402


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        cfg = {
            "marking_exe": "marking.exe",
            "template": "t.hlp",
            "serial_txt": "out/serial.txt",
            "prefix": "HL",
            "seq_max": 20,
        }
        (self.dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.cfg = hl.Config.load(self.dir / "config.json")
        self.day1 = datetime(2026, 11, 10, 9, 0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def read_txt(self):
        return Path(self.cfg.serial_txt).read_bytes().decode()

    def test_one_serial_per_line_crlf(self):
        s = hl.generate(self.cfg, 3, "LOT1", now=self.day1)
        self.assertEqual(s, ["HL2611100001", "HL2611100002", "HL2611100003"])
        self.assertEqual(self.read_txt(), "HL2611100001\r\nHL2611100002\r\nHL2611100003\r\n")

    def test_continues_and_archives_previous(self):
        hl.generate(self.cfg, 2, now=self.day1)
        s = hl.generate(self.cfg, 2, now=self.day1.replace(hour=10))
        self.assertEqual(s, ["HL2611100003", "HL2611100004"])
        self.assertEqual(len(list(Path(self.cfg.archive_dir).iterdir())), 1)

    def test_daily_reset(self):
        hl.generate(self.cfg, 2, now=self.day1)
        s = hl.generate(self.cfg, 1, now=datetime(2026, 11, 11, 8, 0))
        self.assertEqual(s, ["HL2611110001"])

    def test_seq_max_rejected_and_nothing_written(self):
        with self.assertRaises(ValueError):
            hl.generate(self.cfg, 21, now=self.day1)
        self.assertFalse(Path(self.cfg.serial_txt).exists())

    def test_duplicate_format_rejected(self):
        self.cfg.serial_format = "{prefix}{date:%y%m%d}"
        with self.assertRaises(ValueError):
            hl.generate(self.cfg, 2, now=self.day1)

    def test_never_reset_detects_history_duplicate(self):
        self.cfg.seq_reset = "never"
        self.cfg.serial_format = "{prefix}{seq:04d}"
        hl.generate(self.cfg, 2, now=self.day1)
        Path(self.cfg.state_file).unlink()  # state หาย -> เริ่มที่ 1 ใหม่ ต้องจับซ้ำได้
        with self.assertRaises(ValueError):
            hl.generate(self.cfg, 1, now=self.day1)

    def test_history_csv(self):
        hl.generate(self.cfg, 2, "LOT9", now=self.day1)
        lines = Path(self.cfg.history_csv).read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "generated_at,lot,serial")
        self.assertEqual(lines[1], "2026-11-10T09:00:00,LOT9,HL2611100001")

    def test_unknown_config_key(self):
        (self.dir / "bad.json").write_text(json.dumps({
            "marking_exe": "a", "template": "b", "serial_txt": "c", "typo_key": 1}))
        with self.assertRaises(ValueError):
            hl.Config.load(self.dir / "bad.json")


if __name__ == "__main__":
    unittest.main()
