"""วาดรูปจำลองตำแหน่งมาร์กของแต่ละ product (ใช้แทนรูปจริงไปก่อน)

    python tools/make_sample_images.py            -> images/ceramic_box.png, images/lid.png

เปลี่ยนเป็นรูปจริงได้ภายหลังในหน้า Settings ของ UI (เลือกไฟล์รูป) ไม่ต้องแก้โค้ด
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPolygonF

W, H = 800, 600
BG = QColor("#f4f5f7")
INK = QColor("#2b2f36")
MARK = QColor("#d62828")


def fake_datamatrix(p: QPainter, x: float, y: float, size: float, n: int = 14, seed: int = 1) -> None:
    """สี่เหลี่ยมหน้าตาเหมือน DataMatrix (ไม่ใช่โค้ดจริง)"""
    cell = size / n
    rnd = random.Random(seed)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("white"))
    p.drawRect(QRectF(x - cell, y - cell, size + 2 * cell, size + 2 * cell))
    p.setBrush(INK)
    for r in range(n):
        for c in range(n):
            finder = c == 0 or r == n - 1                       # ขอบ L ทึบ
            timing = (r == 0 and c % 2 == 0) or (c == n - 1 and r % 2 == 1)
            if finder or timing or (0 < r < n - 1 and 0 < c < n - 1 and rnd.random() < 0.5):
                p.drawRect(QRectF(x + c * cell, y + r * cell, cell + 0.3, cell + 0.3))


def mark_area(p: QPainter, rect: QRectF, serial: str, seed: int) -> None:
    pad = 8
    dm = min(rect.height() - 2 * pad, rect.width() * 0.45)
    fake_datamatrix(p, rect.x() + pad + 4, rect.y() + (rect.height() - dm) / 2, dm, seed=seed)
    p.setPen(INK)
    p.setFont(QFont("DejaVu Sans Mono", 13, QFont.Bold))
    p.drawText(QRectF(rect.x() + dm + 2 * pad + 8, rect.y(), rect.width() - dm - 3 * pad, rect.height()),
               Qt.AlignVCenter | Qt.AlignLeft, serial)
    pen = QPen(MARK, 3, Qt.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(rect.adjusted(-6, -6, 6, 6))


def callout(p: QPainter, target: QPointF, label_pos: QPointF, text: str) -> None:
    p.setPen(QPen(MARK, 2))
    p.drawLine(label_pos, target)
    p.setBrush(MARK)
    p.drawEllipse(target, 4, 4)
    p.setFont(QFont("DejaVu Sans", 15, QFont.Bold))
    p.drawText(QRectF(label_pos.x() - 120, label_pos.y() + 4, 240, 30), Qt.AlignCenter, text)


def header(p: QPainter, name: str) -> None:
    p.setPen(INK)
    p.setFont(QFont("DejaVu Sans", 22, QFont.Bold))
    p.drawText(QRectF(24, 16, W - 48, 36), Qt.AlignLeft, name)
    p.setFont(QFont("DejaVu Sans", 11))
    p.setPen(QColor("#6b7280"))
    p.drawText(QRectF(24, 52, W - 48, 22), Qt.AlignLeft, "SIMULATED - replace with real photo in Settings")


def iso_box(p: QPainter, x, y, w, d, h, top, side1, side2) -> QPolygonF:
    """กล่อง isometric อย่างง่าย คืนค่า polygon ด้านบน"""
    dx, dy = d * 0.5, -d * 0.35
    top_poly = QPolygonF([QPointF(x, y), QPointF(x + w, y), QPointF(x + w + dx, y + dy), QPointF(x + dx, y + dy)])
    front = QPolygonF([QPointF(x, y), QPointF(x + w, y), QPointF(x + w, y + h), QPointF(x, y + h)])
    right = QPolygonF([QPointF(x + w, y), QPointF(x + w + dx, y + dy), QPointF(x + w + dx, y + dy + h),
                       QPointF(x + w, y + h)])
    p.setPen(QPen(INK, 2))
    for poly, col in ((front, side1), (right, side2), (top_poly, top)):
        p.setBrush(col)
        p.drawPolygon(poly)
    return top_poly


def ceramic_box(path: Path) -> None:
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    header(p, "Ceramic Box")

    # ตัวกล่องเซรามิก มีช่องตรงกลางและแถว pad รอบ ๆ
    x, y, w, d, h = 150, 330, 420, 300, 70
    iso_box(p, x, y, w, d, h, QColor("#e8e2d6"), QColor("#cfc6b5"), QColor("#bdb3a0"))
    dx, dy = d * 0.5, -d * 0.35

    def on_top(u, v):  # u,v ในช่วง 0..1 บนผิวด้านบน
        return QPointF(x + u * w + v * dx, y + v * dy)

    cav = QPolygonF([on_top(0.25, 0.25), on_top(0.75, 0.25), on_top(0.75, 0.75), on_top(0.25, 0.75)])
    p.setBrush(QColor("#9aa3ad"))
    p.drawPolygon(cav)
    p.setBrush(QColor("#c9a227"))
    p.setPen(Qt.NoPen)
    for i in range(12):
        for v in (0.12, 0.88):
            c = on_top(0.12 + i * 0.07, v)
            p.drawEllipse(c, 5, 3.5)

    # ตำแหน่งมาร์ก: มุมซ้ายล่างของด้านหน้า
    area = QRectF(x + 30, y + 8, 260, h - 16)
    mark_area(p, area, "CB26110001", seed=7)
    callout(p, QPointF(area.center().x(), area.bottom() + 6), QPointF(area.center().x() + 40, 500),
            "MARK HERE")
    p.end()
    img.save(str(path))


def lid(path: Path) -> None:
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    header(p, "Lid")

    # ฝาโลหะบาง มองจากด้านบน
    plate = QRectF(170, 120, 460, 340)
    p.setPen(QPen(INK, 2))
    p.setBrush(QColor("#9aa0a6"))
    p.drawRoundedRect(plate.translated(8, 10), 28, 28)  # ขอบความหนา
    p.setBrush(QBrush(QColor("#d5d9de")))
    p.drawRoundedRect(plate, 28, 28)
    p.setPen(QPen(QColor("#b4bac1"), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(plate.adjusted(22, 22, -22, -22), 16, 16)

    # ตำแหน่งมาร์ก: กลางฝา
    area = QRectF(plate.center().x() - 140, plate.center().y() - 40, 280, 80)
    mark_area(p, area, "LD26110001", seed=3)
    callout(p, QPointF(area.center().x(), area.bottom() + 6), QPointF(area.center().x(), 505), "MARK HERE")
    p.end()
    img.save(str(path))


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "images"
    out.mkdir(exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (ต้องมีเพื่อใช้ font)
    ceramic_box(out / "ceramic_box.png")
    lid(out / "lid.png")
    print("saved:", out / "ceramic_box.png", out / "lid.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
