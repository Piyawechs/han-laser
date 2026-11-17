"""dm_reader: อ่าน DataMatrix จากกล้อง Dino-Lite (UVC) หรือจากรูปภาพ  (สำเนาจาก repo dino_capture)

- กล้อง: เปิดผ่าน OpenCV (Windows ใช้ DirectShow) ต้องปิด DinoCapture2 ก่อน เพราะกล้องเปิดได้ทีละโปรแกรม
- ถอดรหัส: zxing-cpp เป็นหลัก ถ้าไม่เจอจะลอง preprocess หลายแบบ แล้วค่อยใช้ pylibdmtx (ถ้าติดตั้งได้) เป็นตัวสุดท้าย
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
import zxingcpp

try:  # pylibdmtx เป็นตัวสำรอง: Windows wheel มี DLL มาด้วย, Linux ต้องมี libdmtx ในเครื่อง
    from pylibdmtx import pylibdmtx as _dmtx
except Exception:  # ImportError, ไม่มี DLL, ไม่มี distutils ฯลฯ
    _dmtx = None

HAS_DMTX = _dmtx is not None


@dataclass
class Result:
    text: str
    points: list = field(default_factory=list)   # [(x, y) * 4] ในพิกัดของภาพต้นฉบับ
    method: str = ""                              # preprocess ที่อ่านได้ เช่น "raw", "clahe", "dmtx"


# ------------------------------------------------------------------ camera
def _backend() -> int:
    return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def open_camera(index: int = 0, width: int | None = 1280, height: int | None = 960) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index, _backend())
    if not cap.isOpened():
        raise RuntimeError(f"เปิดกล้อง index {index} ไม่ได้ (ปิด DinoCapture2 แล้วหรือยัง? ลอง --list)")
    if width and height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


@dataclass
class CameraDevice:
    index: int          # index ของ DirectShow = index ที่ OpenCV ใช้บน Windows
    name: str           # FriendlyName เช่น "Dino-Lite Edge" (กล้องรุ่นเดียวกันชื่อซ้ำกันได้)
    path: str = ""      # DevicePath ไม่ซ้ำกัน ผูกกับ USB port (หรือ serial ของกล้องถ้ามี)


def list_devices() -> list[CameraDevice]:
    """กล้องทั้งหมดเรียงตาม index ของ DirectShow (Windows + pygrabber) ถ้าอ่านไม่ได้คืน []
    เรียกจาก thread ไหนก็ได้ (init COM ให้เอง)"""
    if sys.platform != "win32":
        return []
    try:
        import comtypes
        from comtypes import GUID
        from comtypes.persist import IPropertyBag
        from pygrabber.dshow_graph import SystemDeviceEnum
        from pygrabber.dshow_ids import DeviceCategories
    except Exception:
        return []
    try:
        comtypes.CoInitialize()       # thread ใหม่ (เช่น QThread) ยังไม่มี COM
        inited = True
    except OSError:                   # init ไว้แล้วแบบอื่น ใช้ต่อได้
        inited = False
    out: list[CameraDevice] = []
    try:
        enum = SystemDeviceEnum().system_device_enum.CreateClassEnumerator(
            GUID(DeviceCategories.VideoInputDevice), dwFlags=0)
        try:
            moniker, count = enum.Next(1)
        except ValueError:            # ไม่มีกล้องเลย
            return []
        while count > 0:
            bag = moniker.BindToStorage(0, 0, IPropertyBag._iid_).QueryInterface(IPropertyBag)
            name = bag.Read("FriendlyName", pErrorLog=None)
            try:
                path = bag.Read("DevicePath", pErrorLog=None) or ""
            except Exception:
                path = ""
            out.append(CameraDevice(len(out), str(name), str(path)))
            moniker, count = enum.Next(1)
    except Exception:
        return out
    finally:
        if inited:
            comtypes.CoUninitialize()
    return out


def camera_names() -> list[str]:
    """ชื่อกล้องเรียงตาม index (ต้องใช้ Windows + pygrabber) ถ้าไม่รู้คืน []"""
    return [d.name for d in list_devices()]


def find_dino(names: list[str] | None = None) -> int | None:
    """index ของกล้องตัวแรกที่ชื่อมีคำว่า Dino (เช่น "Dino-Lite Edge") ถ้าไม่เจอคืน None"""
    names = camera_names() if names is None else names
    for i, n in enumerate(names):
        if "dino" in n.lower():
            return i
    return None


def resolve_camera(index: str = "auto", device: str = "", devices: list[CameraDevice] | None = None
                   ) -> tuple[int | None, str]:
    """เลือก index ที่จะเปิด คืน (index, ชื่อ) หรือ (None, เหตุผล)
    device (DevicePath) มาก่อน: ถ้าตั้งไว้แต่ไม่เจอจะไม่เปิดตัวอื่นแทน (กันเปิดกล้องผิดตัว)
    ถ้าไม่ได้ตั้ง device: index = "auto" (Dino ตัวแรก) หรือตัวเลข"""
    devices = list_devices() if devices is None else devices
    if device:
        for d in devices:
            if d.path.lower() == device.lower():
                return d.index, d.name
        if not devices:
            return None, "อ่านรายชื่อกล้องไม่ได้ (ต้องใช้ Windows + pygrabber)"
        return None, "ไม่พบกล้องที่ตั้งไว้ (เสียบ USB port เดิมหรือไม่?)"
    if index == "auto":
        i = find_dino([d.name for d in devices])
        if i is None:
            have = ", ".join(d.name for d in devices)
            return None, "หากล้อง Dino-Lite ไม่เจอ เสียบกล้องแล้วหรือยัง?" + (f"  (กล้องที่มี: {have})" if have else "")
        return i, devices[i].name
    i = int(index)
    return i, devices[i].name if i < len(devices) else f"index {i}"


def list_cameras(max_index: int = 6) -> list[tuple[int, int, int, str]]:
    """คืน [(index, width, height, name)] ของกล้องที่เปิดและอ่านภาพได้ (name = '' ถ้าไม่รู้ชื่อ)"""
    names = camera_names()
    found = []
    for i in range(max(max_index, len(names))):
        cap = cv2.VideoCapture(i, _backend())
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                found.append((i, frame.shape[1], frame.shape[0], names[i] if i < len(names) else ""))
        cap.release()
    return found


# ------------------------------------------------------------------ decode
def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _variants(gray: np.ndarray):
    """(ชื่อ, ภาพ, scale) เรียงจากเร็ว/ทั่วไป ไปหาหนัก; scale = ขนาดภาพนี้ / ภาพต้นฉบับ"""
    yield "raw", gray, 1.0
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    yield "clahe", clahe, 1.0
    blur = cv2.GaussianBlur(clahe, (5, 5), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "otsu", otsu, 1.0
    block = max(15, (min(gray.shape) // 20) | 1)
    yield "adaptive", cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, block, 5), 1.0
    # จุดเลเซอร์ (dot-peen) ห่างกัน: ปิดช่องว่างให้ module ติดกัน
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    yield "close", cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, k), 1.0
    yield "open", cv2.morphologyEx(otsu, cv2.MORPH_OPEN, k), 1.0
    if max(gray.shape) > 1000:
        s = 1000 / max(gray.shape)
        yield "half_clahe", cv2.resize(clahe, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), s


def _zx(img: np.ndarray, method: str, scale: float) -> list[Result]:
    out = []
    for b in zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.DataMatrix):
        if not b.valid or not b.text:
            continue
        p = b.position
        pts = [(int(q.x / scale), int(q.y / scale))
               for q in (p.top_left, p.top_right, p.bottom_right, p.bottom_left)]
        out.append(Result(b.text, pts, method))
    return out


def _dmtx_decode(gray: np.ndarray, timeout_ms: int) -> list[Result]:
    out = []
    h = gray.shape[0]
    for d in _dmtx.decode(gray, timeout=timeout_ms, max_count=4):
        text = d.data.decode("utf-8", "replace")
        r = d.rect  # libdmtx ใช้แกน y จากล่างขึ้นบน
        x0, y0 = r.left, h - r.top - r.height
        pts = [(x0, y0), (x0 + r.width, y0), (x0 + r.width, y0 + r.height), (x0, y0 + r.height)]
        out.append(Result(text, pts, "dmtx"))
    return out


def decode(img: np.ndarray, use_dmtx: bool = True, dmtx_timeout_ms: int = 300,
           methods: list[str] | None = None) -> list[Result]:
    """ถอด DataMatrix ทั้งหมดในภาพ (BGR หรือ grayscale) คืน [] ถ้าไม่เจอ
    methods: จำกัดเฉพาะ preprocess ที่ระบุ (None = ลองทุกแบบจนเจอ)"""
    gray = _gray(img)
    for name, v, scale in _variants(gray):
        if methods and name not in methods:
            continue
        res = _zx(v, name, scale)
        if res:
            return res
    if use_dmtx and HAS_DMTX and (not methods or "dmtx" in methods):
        return _dmtx_decode(gray, dmtx_timeout_ms)
    return []


def draw(frame: np.ndarray, results: list[Result]) -> np.ndarray:
    for r in results:
        if r.points:
            pts = np.array(r.points, np.int32)
            cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
            x, y = pts.min(axis=0)
            cv2.putText(frame, r.text, (int(x), max(20, int(y) - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    return frame


# ------------------------------------------------------------------ reader for integration
class DataMatrixReader:
    """ใช้ตอนต่อกับโปรแกรมอื่น (เช่น han-laser Verify): เปิดกล้องค้างไว้ แล้วเรียก read_once()"""

    def __init__(self, index: int = 0, width: int | None = 1280, height: int | None = 960,
                 use_dmtx: bool = True):
        self.cap = open_camera(index, width, height)
        self.use_dmtx = use_dmtx
        self.last_frame: np.ndarray | None = None

    def read_once(self, timeout: float = 3.0) -> Result | None:
        """อ่านเฟรมไปเรื่อย ๆ จนถอดได้หรือครบ timeout วินาที"""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            self.last_frame = frame
            res = decode(frame, self.use_dmtx)
            if res:
                return res[0]
        return None

    def close(self) -> None:
        self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
