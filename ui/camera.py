"""โหมดกล้อง Dino-Lite: thread อ่านภาพ + ถอด DataMatrix ต่อเนื่อง และตัวกันส่ง serial ซ้ำ"""
from __future__ import annotations

import re

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

PREVIEW_WIDTH = 480


class CodeGate:
    """ส่ง serial ของแต่ละชิ้นแค่ครั้งเดียว

    ชิ้นที่ยังวางอยู่ใต้กล้องจะไม่ถูกส่งซ้ำ ต้องหายไปจากภาพติดกัน clear_after เฟรม
    (เอาชิ้นออก) ก่อนจึงจะส่ง serial เดิมได้อีก ถ้าเปลี่ยนเป็น serial อื่นส่งทันที
    can_accept=False (ยังไม่เลือก EN/WO หรือกำลังส่ง FITS) จะยังไม่นับว่าส่งแล้ว
    """

    def __init__(self, clear_after: int = 15):
        self.clear_after = clear_after
        self.reset()

    def reset(self) -> None:
        self.last: str | None = None
        self.miss = 0

    def feed(self, serial: str | None, can_accept: bool = True) -> str | None:
        if serial is None:
            self.miss += 1
            if self.miss >= self.clear_after:
                self.last = None
            return None
        self.miss = 0
        if serial == self.last or not can_accept:
            return None
        self.last = serial
        return serial


class CameraWorker(QThread):
    """เปิดกล้องแล้ววนอ่านจนกว่าจะ requestInterruption() (import opencv/zxing ใน thread นี้
    เครื่องที่ไม่ได้ติดตั้งจึงยังใช้โหมด USB ได้ตามปกติ)"""

    opened = Signal(str)          # ข้อความบอกว่าเปิดกล้องตัวไหน
    failed = Signal(str)          # เปิด/อ่านกล้องไม่ได้ (thread จบแล้ว)
    codes = Signal(list)          # ข้อความของทุก code ที่อ่านได้ในเฟรมนั้น ([] = ไม่เจอ)
    frame = Signal(QImage)        # ภาพ preview (ย่อแล้ว วาดกรอบ code แล้ว)

    def __init__(self, index: str = "auto", width: int = 1280, height: int = 1024,
                 pattern: re.Pattern | None = None, device: str = "", device_name: str = ""):
        super().__init__()
        self.index, self.width, self.height = index, width, height
        self.device, self.device_name = device, device_name
        self.pattern = pattern            # ใช้แค่เลือกสีกรอบ: serial = เขียว, code อื่น = ส้ม

    def run(self) -> None:
        try:
            import cv2
            import dm_reader as dm
        except Exception as e:  # noqa: BLE001  ไม่มี opencv / zxing-cpp
            self.failed.emit("ใช้กล้องไม่ได้: ยังไม่ได้ติดตั้ง package ของกล้อง\n"
                             f"(.venv\\Scripts\\pip install -r requirements.txt)  [{e}]")
            return
        idx, name = dm.resolve_camera(self.index, self.device)
        if idx is None:
            if self.device:
                name += f"  [{self.device_name or 'กล้องที่เลือกไว้'}]"
            self.failed.emit(name + "  เลือกกล้องได้ในหน้า Settings")
            return
        try:
            cap = dm.open_camera(idx, self.width, self.height)
        except RuntimeError as e:
            self.failed.emit(str(e))
            return
        self.opened.emit(f"{idx}: {name}  {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                         f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        bad = 0
        try:
            while not self.isInterruptionRequested():
                ok, img = cap.read()
                if not ok or img is None:
                    bad += 1
                    if bad > 40:
                        self.failed.emit("อ่านภาพจากกล้องไม่ได้ (สาย USB หลุด หรือโปรแกรมอื่นใช้กล้องอยู่?)")
                        return
                    self.msleep(50)
                    continue
                bad = 0
                res = dm.decode(img, use_dmtx=False)
                self.codes.emit([r.text for r in res])
                self.frame.emit(self._preview(cv2, img, res))
        finally:
            cap.release()

    def _preview(self, cv2, img, results) -> QImage:
        import numpy as np
        for r in results:
            if not r.points:
                continue
            is_serial = self.pattern is None or bool(self.pattern.search("".join(r.text.split()).upper()))
            color = (0, 200, 0) if is_serial else (0, 140, 255)
            cv2.polylines(img, [np.array(r.points, np.int32)], True, color, 4)
        return bgr_to_qimage(cv2, img, PREVIEW_WIDTH)


def bgr_to_qimage(cv2, img, width: int) -> QImage:
    """ภาพ BGR ของ OpenCV -> QImage กว้าง width (สำเนา ไม่อ้าง buffer เดิม)"""
    s = width / img.shape[1]
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
