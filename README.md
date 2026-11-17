# han-laser

สร้างไฟล์ serial number (.txt) ให้ **Han's Laser Marking Control Software V4.0.1**
ใน template ตั้งค่า Serial เป็น **Obtained from files (Each Line)** แล้วโปรแกรม Han's จะอ่านทีละบรรทัด (1 บรรทัด = มาร์ก 1 ชิ้น)

- มีหลาย product (ตอนนี้มี **Ceramic Box** กับ **Lid**) แต่ละตัวมีรูปแบบ serial, template `.hs`, ไฟล์ `.txt` และรูปตำแหน่งมาร์กของตัวเอง
- ประวัติการสร้างทั้งหมดเก็บใน SQLite (`data/han_laser.db`) และกันไม่ให้ serial ซ้ำ
- มี UI (PySide6) และ CLI ให้ใช้

## ติดตั้ง (บน Windows PC ที่ต่อกับเครื่องมาร์ก)
```
git clone https://github.com/Piyawechs/han-laser.git
cd han-laser
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```
ต้องมี Python 3.9 ขึ้นไป
`start_ui.bat` จะใช้ Python ใน `.venv` ของโปรเจกต์ก่อน ถ้าไม่มี `.venv` จึงใช้ `pythonw` ของเครื่อง

## เปิด UI
ดับเบิลคลิก `start_ui.bat` หรือ `han_laser_ui.pyw`
ครั้งแรกโปรแกรมจะสร้าง `config.json` จาก `config.example.json` ให้เอง

| หน้า | ใช้ทำอะไร |
|---|---|
| **Verify** (หน้าแรก) | เลือก EN, Shift, Workorder, iQR code → สแกน code ของชิ้นที่มาร์กแล้ว (เครื่องสแกน USB หรือกล้อง Dino-Lite) → ขึ้น **PASS** (เขียว) หรือ **FAIL** (แดง) และบันทึกทุกครั้ง |
| **Generate** | เลือก product → ดูรูปตำแหน่งมาร์กและ serial ตัวถัดไป → กรอก Lot และจำนวน → **Generate serial** (มีหน้ายืนยันก่อน) → **เปิด template** |
| **History** | ดูชุดที่สร้างไปแล้ว กรองตาม product หรือ lot ได้ ดับเบิลคลิกแถวเพื่อดูหรือ copy serial ทั้งชุด |
| **Settings** (Engineer mode) | แก้ชื่อ, prefix, รูปแบบ, path ของ template / .txt / รูป และเพิ่มหรือลบ product แล้วกด **บันทึก** |

### Verify (ตรวจหลังมาร์ก)
- เครื่องสแกน USB ทำงานเหมือนคีย์บอร์ด สแกนแล้วกด Enter ให้เอง โปรแกรมจะตรวจทันทีและล้างช่องรอสแกนตัวถัดไป
- **PASS** เมื่อ serial เคยถูก generate, อยู่ใน Workorder ที่เลือก และยังไม่เคย PASS มาก่อน
- **FAIL** มี 3 แบบ:
  - **ไม่พบในระบบ**: ไม่เคย generate
  - **ผิด Workorder**: serial อยู่ใน Workorder อื่น
  - **ซ้ำ**: เคย PASS ไปแล้ว ข้อความจะบอกเวลาและ EN ของครั้งแรก
- **iQR code** เป็นค่าที่เลือกจาก dropdown (ไม่ได้สแกน) และบันทึกคู่กับ serial ทุกครั้ง
- ทุกการสแกนเก็บในตาราง `verifications` ของ SQLite บันทึกเวลา, ค่าที่สแกนได้, serial, product, EN, Shift, Workorder, iQR, ผล และสาเหตุ
- รายการใน dropdown (EN, Shift, Workorder, iQR code) Engineer ตั้งได้ที่หน้า Settings → แท็บ "Verify และทั่วไป" บรรทัดละ 1 รายการ
- **Workorder = Lot ตอน Generate** ช่อง Workorder ในหน้า Generate ใช้รายการชุดเดียวกัน

### โหมดกล้อง Dino-Lite (อ่าน DataMatrix ต่อเนื่อง)
หน้า Verify เลือก **รับค่าจาก**: **เครื่องสแกน USB** หรือ **กล้อง Dino-Lite** สลับได้ตลอด โปรแกรมจำว่าใช้แบบไหนไว้ใน `config.json`
- เลือกกล้องแล้วจะมีภาพจากกล้องด้านขวา วางชิ้นงานใต้กล้อง อ่านได้แล้วตรวจทันที (ไม่ต้องกดอะไร)
- ชิ้นที่ยังวางอยู่จะ**ไม่ตรวจซ้ำ** ต้องเอาออกจากกล้องก่อน (ไม่เห็น ~15 เฟรม) ถ้าวางชิ้นเดิมกลับมาจะตรวจอีกครั้งและขึ้น "ซ้ำ"
- ชิ้นงานมีหลาย code ได้: ส่งไป verify เฉพาะ code ที่ตรง **Serial regex** (กรอบเขียว) code อื่นเป็นกรอบส้มและไม่ถูกตรวจ
- ถ้ายังไม่เลือก EN / Shift / Workorder / iQR หรือกำลังส่ง FITS จะรอ แล้วตรวจชิ้นที่วางอยู่เมื่อพร้อม
- **ต้องปิด DinoCapture2 ก่อน** เพราะกล้องเปิดได้ทีละโปรแกรม ถ้าเปิดกล้องไม่ได้จะขึ้นข้อความสีแดงและปุ่ม **เชื่อมต่อกล้องใหม่**

ตั้งค่าที่ Settings → "Verify, FITS และทั่วไป" → **กล้อง Dino-Lite**
- **กล้อง (index)**: `auto` = กล้องตัวแรกที่ชื่อมีคำว่า Dino (ไม่ไปเปิดกล้องในตัวโน้ตบุ๊ก) หรือใส่เลข index เอง
- **Serial regex**: ว่างไว้ = ขึ้นต้นด้วย prefix ของ product (เช่น `^(?:CB|LD)`) ไม่สนตัวพิมพ์เล็ก/ใหญ่

ติดตั้ง package ของกล้อง (อยู่ใน `requirements.txt` แล้ว ถ้าติดตั้งก่อนหน้านี้ให้รันอีกครั้ง):
`.venv\Scripts\pip install -r requirements.txt`
ใช้ `opencv-python-headless` (ห้ามลง `opencv-python` ใน `.venv` เดียวกัน เพราะมี Qt ของตัวเองซึ่งชนกับ PySide6)
ถ้าไม่ได้ติดตั้ง ยังใช้เครื่องสแกน USB ได้ตามปกติ
ตัวอ่านกล้อง `dm_reader.py` คัดลอกมาจาก repo `dino_capture` (ใช้ทดลองกล้องแยกได้)

### FITS (handshake + log หลัง verify)
ถ้าเปิดใช้ใน Settings แต่ละชิ้นที่**ตรวจในเครื่องผ่าน**จะทำต่อตามลำดับนี้:
1. ส่ง FITS **handshake** (model, operation, serial)
2. ถ้า handshake ผ่าน ส่ง **log** ตาม parameter ที่ตั้งไว้ ได้ PASS เมื่อผ่านครบ

ชิ้นที่ตรวจในเครื่องไม่ผ่าน (ไม่พบ / ผิด Workorder / ซ้ำ) จะไม่ถูกส่งไป FITS

ถ้า FITS ปฏิเสธ หรือเน็ตล่ม / FITS ไม่ตอบ จะขึ้น **FAIL** และมีปุ่ม **ส่ง FITS ซ้ำ** หรือดับเบิลคลิกแถวนั้นในตาราง
ถ้า handshake ผ่านไปแล้ว การส่งซ้ำจะส่งแค่ log
ผลของ handshake และ log จะบันทึกลง DB คู่กับการสแกน (คอลัมน์ `fits_handshake`, `fits_log`, `fits_message`)

**ติดตั้ง**
- ติดตั้ง wheel ของ FITS client ใน `.venv`: `.venv\Scripts\pip install fabrinet_fits_client-*.whl`
- คัดลอก `.env.example` เป็น `.env` ในโฟลเดอร์ han-laser แล้วกรอกค่าจริง (FITS_URL, FITS_PROJECT_ID, FITS_USER, FITS_PASSWORD, FITS_REVISION)
  - โปรแกรมอ่าน `.env` เองตอนเปิด (ทั้ง UI และ CLI) ค่าใน `.env` ชนะตัวแปรที่ตั้งไว้ใน Windows
  - ค่าที่ยังเป็น `<...>` นับว่ายังไม่ได้ตั้ง แก้ `.env` แล้วต้องเปิดโปรแกรมใหม่
  - `.env` อยู่ใน .gitignore ห้าม commit
- Settings → "Verify, FITS และทั่วไป" → ตั้งค่า **Model**, **Operation** และ **Parameters** (บรรทัดละ `ชื่อ parameter = ค่า` เรียงตามลำดับใน FITS)
  - ส่วน "การเชื่อมต่อ" แสดงว่าตั้ง FITS_* ครบหรือยัง แต่ไม่แสดงค่าจริง
- ค่าคงที่ที่ใช้ได้ในช่อง Parameters: `NA` (ส่งข้อความ NA), `-` (ส่งเครื่องหมาย -), `blank` (ส่งค่าว่าง) เช่น `Failure code = NA`
- ช่อง Workorder ใส่ WO PN คู่กันได้ เช่น `WO-001 = PN-123`

**โหมด Engineer (TEST)** เลือกได้ที่ช่อง "โหมด" ในหน้า Verify ต้องใส่รหัส Engineer
- สแกน SN ปกติ แล้วโปรแกรมเติม `_test` ให้เอง เช่น `CB26110001` → `CB26110001_test`
- ส่งไป **FITS TEST endpoint** จริง
  - ใช้ `FITS_TEST_URL` ถ้าตั้งไว้ ถ้าไม่ตั้งจะใช้ TEST URL ที่มากับ fits_client
  - ใช้ `FITS_TEST_USER`, `FITS_TEST_PASSWORD`, `FITS_TEST_PROJECT_ID`, `FITS_TEST_REVISION` ใน `.env` ถ้าตั้งไว้ ถ้าไม่ตั้งจะใช้ FITS_* ตัวปกติ
- ยังเช็กว่า serial มีในระบบและตรง Workorder แต่**ไม่เช็กซ้ำ** (ทดลองซ้ำได้) และไม่นับรวมในยอดผ่านของ Workorder
- ในประวัติขึ้นเป็น `PASS TEST` / `FAIL TEST`
- โหมด Operator ไม่รับ SN ที่ลงท้าย `_test`
- กด "ออกจาก Engineer mode" แล้วจะกลับเป็นโหมด Operator

### Engineer mode
- หน้า Settings ถูกล็อกไว้ ต้องกด **เข้าสู่ Engineer mode** แล้วใส่รหัสผ่าน
- ครั้งแรกที่ยังไม่มีรหัส โปรแกรมจะให้ตั้งรหัสใหม่ (อย่างน้อย 4 ตัว)
- เปลี่ยนรหัสได้ที่ปุ่ม **เปลี่ยนรหัสผ่าน Engineer** ในหน้า Settings
- กด **ออกจาก Engineer mode** ที่มุมขวาล่าง หรือปิดโปรแกรม จะกลับไปล็อก (การแก้ที่ยังไม่บันทึกจะหาย)
- รหัสเก็บใน `config.json` เป็น hash (`engineer_password`) ไม่เก็บรหัสจริง
- **ลืมรหัส:** ปิดโปรแกรม แล้วลบค่าใน `"engineer_password"` ของ `config.json` ให้เป็น `""` จากนั้นเปิดใหม่และตั้งรหัสใหม่
- ระบบนี้กันไม่ให้ operator แก้การตั้งค่าโดยไม่ตั้งใจ ไม่ได้กันคนที่แก้ไฟล์ `config.json` ได้โดยตรง

## ตั้งค่า template ใน Han's (ทำครั้งเดียวต่อ product)
1. ดับเบิลคลิก object barcode หรือ text เพื่อเปิด Barcode setup → เลือก **Serial** → กด **Set...**
2. ในหน้า Serial setup เลือก **Obtained from files (Each Line)** → กด **Set...** → เลือกไฟล์ `.txt` ของ product นั้น (ตรงกับช่อง "ไฟล์ serial .txt" ในหน้า Settings)
3. กด OK แล้ว Save template (.hs)

## รูปแบบ serial
ช่องรูปแบบใช้ Python format และมีตัวแปรให้ใช้ดังนี้:
- `{prefix}`
- `{date:%y%m}` (ใช้ strftime ได้ทุกแบบ)
- `{seq:04d}` (เลขลำดับ ต้องมีเสมอ)

| Product | รูปแบบ | ตัวอย่าง | เริ่มเลขใหม่ |
|---|---|---|---|
| Ceramic Box | `CB` + `{date:%y%m}{seq:04d}` | `CB26110001` | ทุกเดือน |
| Lid (ค่าสมมติ รอยืนยัน) | `LD` + `{date:%y%m}{seq:04d}` | `LD26110001` | ทุกเดือน |

ค่า "เริ่มเลขใหม่" (`seq_reset`) ต้องสอดคล้องกับวันที่ในรูปแบบ:
- มี `%y%m` ให้ใช้ `monthly`
- มี `%y%m%d` ให้ใช้ `daily`
- ไม่มีวันที่ ให้ใช้ `never`

ถ้าไม่สอดคล้องกัน เลขจะซ้ำ และโปรแกรมจะไม่ยอมสร้าง

## รูปตำแหน่งมาร์ก
`images/ceramic_box.png` กับ `images/lid.png` เป็น**รูปจำลอง** (วาดด้วย `tools/make_sample_images.py`)
ถ้าจะเปลี่ยนเป็นรูปจริง ให้ไปที่หน้า Settings → ช่อง "รูปตำแหน่งมาร์ก" → Browse แล้วกดบันทึก ไม่ต้องแก้โค้ด

## CLI
```
python han_laser.py status                                  # serial ตัวถัดไปของทุก product
python han_laser.py -p ceramic_box generate -n 100 --lot LOT001
python han_laser.py -p lid launch                           # เปิด template ของ lid
python han_laser.py -p lid run -n 50 --lot LOT002           # generate แล้ว launch
```

## ไฟล์ข้อมูล (`data/`, ไม่อยู่ใน git)
- `han_laser.db`: SQLite มีตาราง `batches` (แต่ละครั้งที่สร้าง) และ `serials` (ทุกตัว ซ้ำไม่ได้)
- `archive/`: สำเนาไฟล์ .txt เดิมก่อนถูกเขียนทับ

ไฟล์ serial `.txt` อยู่ที่ `serial/` ในโฟลเดอร์โปรเจกต์ (ค่าเริ่มต้น) และไม่อยู่ใน git ใน Serial setup ของ template ให้ชี้มาที่ไฟล์ในโฟลเดอร์นี้ หรือเปลี่ยน path ในหน้า Settings

การ generate ทำใน transaction ถ้าเขียนไฟล์ .txt ไม่สำเร็จ จะไม่มีอะไรถูกบันทึกลง DB
ไฟล์ `history.csv` และ `state.json` ของเวอร์ชันก่อนเลิกใช้แล้ว ลบทิ้งได้

## ข้อควรระวัง
- ถ้าสร้างไฟล์ใหม่ทับไฟล์เดิมระหว่างที่โปรแกรม Han's ยังเปิดอยู่ ต้องเช็กว่าตัวชี้บรรทัดรีเซ็ตกลับไปบรรทัดแรกหรือไม่
- ถ้าตัวอักษรเพี้ยน ให้ลองเปลี่ยน Encoding ในหน้า Settings

## เทสต์
```
python -m unittest discover -s tests -v       # เทสต์ UI จะถูกข้ามถ้าไม่มี PySide6
```
