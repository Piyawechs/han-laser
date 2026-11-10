# han-laser

สร้างไฟล์ serial number (.txt) ให้ **Han's Laser Marking Control Software V4.0.1**
ใน template ตั้งค่า variable text ให้อ่านจากไฟล์ทีละบรรทัด (1 บรรทัด = มาร์ก 1 ชิ้น)

## ติดตั้ง (บน Windows PC ที่ต่อกับเครื่องมาร์ก)
- Python 3.9 ขึ้นไป ไม่ต้องติดตั้ง package เพิ่ม
- `copy config.example.json config.json` แล้วแก้ค่า:
  - `marking_exe`: path ของโปรแกรม Han's
  - `template`: ไฟล์ template
  - `serial_txt`: ไฟล์ .txt ที่ตั้งไว้ใน template
  - `serial_format`, `prefix`: รูปแบบ serial

## ใช้งาน
```
python han_laser.py status                        # ดูเลขล่าสุดและตัวถัดไป
python han_laser.py generate -n 100 --lot LOT001  # สร้างไฟล์ serial 100 บรรทัด
python han_laser.py launch                        # เปิดโปรแกรมมาร์กพร้อม template
python han_laser.py run -n 100 --lot LOT001       # generate แล้ว launch
```

## รูปแบบ serial
`serial_format` ใช้ Python format และมีตัวแปรให้ใช้ดังนี้:
- `{prefix}`
- `{date:%y%m%d}` (ใช้ strftime ได้ทุกแบบ)
- `{seq:04d}` (เลขลำดับ)

ค่าเริ่มต้น: `"{prefix}{seq:04d}"` กับ `prefix: "CB"` จะได้ `CB0001`, `CB0002`, ...
(ถ้าอยากใส่วันที่: `"{prefix}{date:%y%m%d}{seq:04d}"` จะได้ `CB2611100001`)

ถ้ารูปแบบไม่มีวันที่ ต้องใช้ `seq_reset: "never"` ไม่อย่างนั้นวันรุ่งขึ้นจะเริ่มที่ 0001 ใหม่ และโปรแกรมจะไม่ยอมสร้างเพราะเลขซ้ำ

`seq_reset` มี 2 ค่า:
- `daily`: เริ่มลำดับใหม่ทุกวัน
- `never`: นับต่อไปเรื่อย ๆ

## ไฟล์ข้อมูล (`data/`)
- `state.json`: เลขลำดับล่าสุด
- `history.csv`: serial ทุกตัวที่เคยสร้าง ใช้กันเลขซ้ำ
- `archive/`: สำเนาไฟล์ .txt เดิมก่อนถูกเขียนทับ

## ข้อควรระวัง
- ถ้าสร้างไฟล์ใหม่ทับไฟล์เดิมระหว่างที่ซอฟต์แวร์ Han's ยังเปิดอยู่ ต้องเช็กว่าตัวชี้บรรทัดของซอฟต์แวร์รีเซ็ตกลับไปบรรทัดแรกหรือไม่
- ถ้าตัวอักษรเพี้ยน ให้ลองเปลี่ยน `txt_encoding` เป็น `utf-8-sig`, `gbk` หรือ `cp874`

## เทสต์
```
python -m unittest discover -s tests -v
```
