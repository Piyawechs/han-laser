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
| **Verify** (หน้าแรก) | เลือก EN, Shift, Workorder → สแกน QR code ของชิ้นที่มาร์กแล้ว → ขึ้น **PASS** (เขียว) หรือ **FAIL** (แดง) และบันทึกทุกครั้ง |
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
- ทุกการสแกนเก็บในตาราง `verifications` ของ SQLite บันทึกเวลา, ค่าที่สแกนได้, serial, product, EN, Shift, Workorder, ผล และสาเหตุ
- รายการใน dropdown (EN, Shift, Workorder) Engineer ตั้งได้ที่หน้า Settings → แท็บ "Verify และทั่วไป" บรรทัดละ 1 รายการ
- **Workorder = Lot ตอน Generate** ช่อง Workorder ในหน้า Generate ใช้รายการชุดเดียวกัน

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
