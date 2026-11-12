"""han-laser UI (PySide6) ดับเบิลคลิกไฟล์นี้ หรือรัน start_ui.bat

    pip install -r requirements.txt
    pythonw han_laser_ui.pyw [config.json]
"""
from __future__ import annotations

import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("han-laser")
    app.setStyle("Fusion")

    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config.json"
    if not cfg.exists():
        shutil.copy(ROOT / "config.example.json", cfg)  # เปิดครั้งแรก

    def excepthook(exc_type, exc, tb):  # pythonw ไม่มี console ให้เห็น error
        QMessageBox.critical(None, "han-laser error", "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.excepthook = excepthook

    try:
        win = MainWindow(cfg)
    except Exception as e:  # config เสีย ฯลฯ
        QMessageBox.critical(None, "han-laser", f"เปิดไม่ได้: {e}\n\nตรวจไฟล์ {cfg}")
        return 1
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
