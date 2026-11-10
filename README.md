# han-laser

สร้างไฟล์ serial number (.txt) ให้ **Han's Laser Marking Control Software V4.0.1**
ใน template ตั้งค่า variable text ให้อ่านจากไฟล์ทีละบรรทัด (1 บรรทัด = มาร์ก 1 ชิ้น)

## ติดตั้ง (บน Windows PC ที่ต่อกับเครื่องมาร์ก)
- Python 3.9 ขึ้นไป ไม่ต้องติดตั้ง package เพิ่ม
- `copy config.example.json config.json` แล้วแก้ค่า:
  - `template`: ไฟล์ template `.hs` เช่น `C:/Users/Administrator/Desktop/Back up/test2.hs`
  - `marking_exe`: เว้นว่างได้ ถ้าว่างจะเปิด `.hs` ด้วยโปรแกรมที่ Windows ผูกไว้ (HS Microsoft) เหมือนดับเบิลคลิกไฟล์
  - `serial_txt`: ไฟล์ .txt ที่ตั้งไว้ใน template
  - `serial_format`, `prefix`: รูปแบบ serial

## ตั้งค่า template ใน Han's (ทำครั้งเดียว)
1. ดับเบิลคลิก object barcode หรือ text เพื่อเปิด Barcode setup → เลือก **Serial** → กด **Set...**
2. ในหน้า Serial setup เลือก **Obtained from files (Each Line)** → กด **Set...** → เลือกไฟล์ `serial.txt` (ไฟล์เดียวกับ `serial_txt` ใน config)
3. กด OK แล้ว Save template (.hs)

(ถ้าเลือก **Obtained from files (First Line)** จะอ่านแค่บรรทัดแรกทุกครั้งที่มาร์ก)

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

ค่าเริ่มต้นคือ `CB` + ปี 2 หลัก + เดือน 2 หลัก + ลำดับ 4 หลัก (`CBYYMM0001`)
```
"serial_format": "{prefix}{date:%y%m}{seq:04d}",
"prefix": "CB",
"seq_reset": "monthly"
```
จะได้ `CB26110001`, `CB26110002`, ... และเดือนถัดไปเริ่มใหม่ที่ `CB26120001`

`seq_reset` ต้องสอดคล้องกับวันที่ใน `serial_format`:

| serial_format | seq_reset |
|---|---|
| มี `%y%m` | `monthly` |
| มี `%y%m%d` | `daily` |
| ไม่มีวันที่ เช่น `"{prefix}{seq:04d}"` | `never` |

ถ้าไม่สอดคล้องกัน เลขจะซ้ำ และโปรแกรมจะไม่ยอมสร้างไฟล์

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
