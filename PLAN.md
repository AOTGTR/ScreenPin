# ScreenPin — แผนออกแบบ (จัดแอพข้ามจอ + จำจอ)

> เป้าหมาย: ย้ายหน้าต่างแอพข้ามจอให้ **เร็วที่สุด** + **จำจอได้ถาวร** แม้ปิด/เปิดจอ
> และเลข Display 1-2-3 ของ Windows สลับไปมา

---

## 1. Stack

| ส่วน | เลือก | เหตุผล |
|---|---|---|
| ภาษา | **Python 3.13** (มีในเครื่อง) | ไม่มี .NET SDK ในเครื่อง |
| Win32 | **ctypes** ล้วน | zero dependency ไม่ต้อง pip install |
| GUI | **HTML/CSS/JS ใน Edge app-window** | tkinter หน้าตาสู้ไม่ได้ · Edge มีอยู่แล้วใน Win11 ไม่ต้องลงอะไรเพิ่ม |
| GUI ↔ Python | HTTP บน `127.0.0.1` + token (long-poll) | ง่าย เร็ว ใช้ stdlib `http.server` |
| Overlay picker | **Win32 GDI** (ไม่ใช้ toolkit) | ต้องโผล่ทันที เปิดเบราว์เซอร์ไม่ทัน |
| Tray | `Shell_NotifyIconW` ผ่าน ctypes | ไม่ต้องใช้ pystray/pillow |
| รัน | `pythonw.exe` ผ่าน `.vbs` | ไม่มีหน้าต่าง console โผล่ |

**ผลลัพธ์: ลง 0 package. copy โฟลเดอร์ไปเครื่องอื่นก็รันได้**

> อัปเดตหลัง build: เดิมวางแผนใช้ tkinter แต่หน้าตาไม่ผ่าน จึงเปลี่ยนชั้น UI
> เป็นหน้าเว็บที่ Python เสิร์ฟเองแล้วเปิดด้วย `msedge --app` — logic Win32
> ที่เทสผ่านแล้วใช้ต่อทั้งหมด

---

## 2. ปัญหาหลัก: จะระบุ "จอ" ยังไงให้ไม่หลุด

Windows เรียกจอว่า `\.\DISPLAY1/2/3` แต่**เลขนี้สลับได้**เมื่อปิด/เปิดจอ →
ใช้เป็น ID ไม่ได้เด็ดขาด

### ข้อมูลจริงจากเครื่องนี้ (probe แล้ว)

```
DISPLAY1  IPS0001  UID4355  edid_sn=1     (0,0,1920,1080)  ← primary
DISPLAY2  TXD0000  UID4352  edid_sn=6666  (-3840,0)        ← ซ้ายสุด
DISPLAY3  IPS0001  UID4353  edid_sn=0     (-1920,0)        ← กลาง
```

จอ 2 ตัวเป็นรุ่นเดียวกัน (`IPS0001`) และ **ไม่มี EDID serial string** →
ใช้ PnP ID เดี่ยวๆ ไม่พอ

### MonitorKey ที่ออกแบบ

```
key = "<PnPID>|<edid_serial_number>|<UID>"
เช่น "IPS0001|1|UID4355"
```

ดึงจาก:
1. `EnumDisplayDevices(EDD_GET_DEVICE_INTERFACE_NAME)` → `DISPLAY#IPS0001#5&xx&0&UID4355#{guid}`
2. registry `SYSTEM\CurrentControlSet\Enum\DISPLAY\<pnp>\<inst>\Device Parameters\EDID`
   → serial number (byte 12-16), friendly name (descriptor 0xFC)

### ถ้าย้ายสายไปพอร์ตอื่น key จะเปลี่ยน → ใช้ระบบ match แบบให้คะแนน

| เงื่อนไข | คะแนน |
|---|---|
| key ตรงเป๊ะ | 100 |
| pnp + edid_sn ตรง (ย้ายพอร์ต) | 80 |
| pnp + uid ตรง | 70 |
| pnp + ความละเอียดเดียวกัน | 50 |
| ไม่ตรง | 0 |

จับคู่แบบ greedy คะแนนสูงสุดก่อน → **ย้ายสายจอแล้ว tag ยังตามไป**

### Tag (ชื่อที่ผู้ใช้ตั้ง)

ทุกอย่างในแอพอ้างอิงด้วย **tag** ไม่ใช่เลข Display
เช่น `"กลาง"`, `"ซ้าย"`, `"TV"` — ตั้งครั้งเดียวจำถาวร
+ มี **slot 1-4** สำหรับผูก hotkey (slot ผูกกับ tag ไม่ใช่ตำแหน่ง)

---

## 3. ย้ายแอพข้ามจอ — 6 วิธี เรียงจากเร็วสุด

| # | วิธี | Hotkey | จำนวนคลิก |
|---|---|---|---|
| 1 | ย้ายหน้าต่างที่ focus ไปจอ**ข้างๆ** | `Ctrl+Alt+←/→` | 0 |
| 2 | ย้ายหน้าต่างที่ focus ไป**slot 1-4** | `Ctrl+Alt+1..4` | 0 |
| 3 | **อพยพทั้งจอ** ไปจอข้างๆ (ก่อนปิดจอ) | `Ctrl+Alt+Shift+←/→` | 0 |
| 4 | **Overlay picker** — แผนที่จอโผล่กลางจอ กดเลข | `Ctrl+Alt+Q` | 1 คีย์ |
| 5 | หน้าหลัก: list หน้าต่าง + ปุ่ม `[1][2][3]` ทุกแถว | — | 1 คลิก |
| 6 | **Rule อัตโนมัติ** — แอพเปิดมาปุ๊บเข้าจอที่กำหนดเอง | — | 0 |

> ของ Windows เอง (`Win+Shift+←`) วนจอมั่ว + ขนาดเพี้ยน → ของเราคุมด้วย tag + คืนขนาดเดิม

---

## 4. Logic การย้าย (ไม่ให้ขนาดเพี้ยน)

เก็บตำแหน่งเป็น **สัดส่วน (ratio) ของ work area** ไม่ใช่ pixel:

```
ratio = ((x-wx)/ww, (y-wy)/wh, w/ww, h/wh)  + flag maximized
```

ย้าย:
1. `GetWindowPlacement` → ถ้า maximized: `SW_RESTORE` ก่อน
2. คำนวณ rect ใหม่จาก ratio บน work area ของจอปลายทาง
3. clamp ให้อยู่ในจอเสมอ (**กันจม** — ห้าม title bar หลุดขอบ)
4. `SetWindowPos(SWP_NOZORDER|SWP_NOACTIVATE)`
5. ถ้าเดิม maximized → `SW_MAXIMIZE` คืน

---

## 5. ตัวแอพเองอยู่จอไหน (โจทย์หลักของผู้ใช้)

```json
"self": { "chain": ["จอ3", "จอ2"], "follow": true }
```

**Resolve chain ทุกครั้งที่จอเปลี่ยน:**

```
จอ3 มี?  → ไปจอ3           ← จอหลัก
จอ2 มี?  → ไปจอ2           ← จอรอง
ไม่มีทั้งคู่ → เลือกจอที่ "ว่างสุด"  ← กันจม ไม่หายไปไหน
```

**จอหลักกลับมา = เด้งกลับทันที** แม้ตอนนั้นอยู่จอ 1
(`follow: true` — เช็คทุกครั้งที่ display เปลี่ยน)

จำ rect แยกรายจอ → กลับจอไหนก็ได้ตำแหน่งเดิมของจอนั้น

---

## 6. จำจอของแอพอื่น + คืนอัตโนมัติ

**แก้ระหว่าง build:** จำแบบ "ต่อ exe" อย่างเดียวไม่พอ — Chrome/Explorer เปิดหลาย
หน้าต่างคนละจอจะทับกันเอง จึงเป็น 2 ชั้น:

| ชั้น | ขอบเขต | ใช้ตอน |
|---|---|---|
| session memory | ต่อ **hwnd** | หน้าต่างยังเปิดอยู่ (คืนจอตอนจอกลับมา) |
| app memory (config) | ต่อ **exe** | เปิดแอพใหม่ / รีสตาร์ทเครื่อง |

ลำดับ: `pin` > session > app

```json
"apps": {
  "discord.exe": { "mode": "remember", "chain": ["จอ3"], "rect": {...} }
}
```

| mode | พฤติกรรม |
|---|---|
| `remember` (default) | ย้ายเองครั้งไหน จำครั้งนั้น → เปิดใหม่/จอกลับมา = คืนที่เดิม |
| `pin` | บังคับอยู่ chain นี้เสมอ |
| `ignore` | ไม่ยุ่ง |

**ตอนปิดจอ:** snapshot ทุกหน้าต่าง (tag + ratio) ก่อน Windows ยัดมารวมจอเดียว
**ตอนเปิดจอ:** คืนทุกหน้าต่างที่ tag นั้นกลับมาแล้ว

---

## 6.1 กันความจำเพี้ยน (เจอตอนเทส)

| สถานการณ์ | ถ้าไม่กัน | วิธีกัน |
|---|---|---|
| จอที่จำไว้ถูกปิด → Windows ยัดหน้าต่างไปจออื่น | จำทับเป็นจอใหม่ เปิดจอกลับมาก็ไม่คืน | ไม่อัปเดต tag ถ้า tag เดิมยัง offline |
| กด "อพยพ" ก่อนปิดจอ | จอเดิมยัง online → จำทับทันที | mark เป็น `displaced` ไม่ให้ learn ทับจนกว่าจะกลับบ้าน |
| หน้าต่าง UI ของเราเองเป็น `msedge.exe` | engine เอา memory ของ Edge จริงมาย้าย UI ตัวเอง | `ignore_hwnds` + guard ช่วง browser กำลัง start |

## 7. Watcher — รู้ทันทีที่จอเปลี่ยน

- **`WM_DISPLAYCHANGE`** ที่หน้าต่างซ่อน → ทันที (0 delay)
- **poll ทุก 1s** เทียบ signature (`set(key)+rect`) → safety net เผื่อ event หาย
- debounce 700ms (จอเปิดมาแล้ว Windows ยัง re-layout อยู่ ต้องรอให้นิ่ง)

---

## 8. โครงไฟล์

```
e:\app\จอ\
├─ PLAN.md
├─ README.md
├─ ScreenPin.vbs          ← ดับเบิลคลิกเปิด (ไม่มี console)
├─ run.bat                ← เปิดแบบเห็น log (debug)
├─ main.py
├─ config.json            ← สร้างอัตโนมัติ
└─ screenpin/
   ├─ win32.py     ctypes: struct + API ทั้งหมด
   ├─ monitors.py  enum จอ, MonitorKey, EDID, matching
   ├─ windows.py   enum หน้าต่าง, move/place, ratio
   ├─ config.py    JSON load/save + migration
   ├─ engine.py    rules + reconcile + self-placement
   ├─ msgloop.py   thread: hotkey + tray + WM_DISPLAYCHANGE
   ├─ picker.py    overlay เลือกจอ (GDI, อยู่ใน msgloop thread)
   ├─ server.py    HTTP API (127.0.0.1 + token)
   ├─ browser.py   คุมหน้าต่าง Edge (หา/ย้าย/ซ่อน)
   ├─ shortcut.py  สร้าง .lnk ผ่าน COM IShellLinkW
   ├─ app.py       controller + main loop
   └─ web/         index.html · app.css · app.js
```

**3 thread:** main (engine tick ทุก 1s) · msgloop (Win32/hotkey/tray/picker) ·
http (เสิร์ฟหน้าเว็บ + API) — คุยกันผ่าน `queue.Queue` + `RLock`

---

## 9. หน้าตา UI

```
┌─ ScreenPin ─────────────────────────────────────────┐
│ [ จอ ]  [ หน้าต่าง ]  [ กฎ ]  [ ตั้งค่า ]           │
├─────────────────────────────────────────────────────┤
│  แผนที่จอ (คลิกเพื่อตั้ง tag)                        │
│   ┌────┐ ┌────┐ ┌────┐                              │
│   │ ซ้าย│ │กลาง │ │ ขวา │  ● = ตัวแอพอยู่ตรงนี้      │
│   │ [1]│ │ [2]│ │●[3]│                              │
│   └────┘ └────┘ └────┘                              │
├─────────────────────────────────────────────────────┤
│  หน้าต่างที่เปิดอยู่           จอ    ย้ายไป          │
│  Chrome — YouTube            กลาง   [1][2][3] [📌]  │
│  Discord                     ขวา    [1][2][3] [📌]  │
│  VS Code                     ซ้าย   [1][2][3] [📌]  │
└─────────────────────────────────────────────────────┘
```

- `📌` = pin แอพนี้ไว้จอนี้ถาวร
- แถบล่าง: จอหลักของแอพ / จอรอง (dropdown เลือก tag)

---

## 10. ข้อจำกัดที่ต้องรู้

| เรื่อง | ผล | ทางแก้ |
|---|---|---|
| แอพรัน as Admin | ย้ายไม่ได้ (UIPI block) | รัน ScreenPin as Admin |
| เกม fullscreen exclusive | ย้ายไม่ได้ | ใช้ borderless แทน |
| UWP ที่ suspend อยู่ | ย้ายแล้วเด้งกลับ | เช็ค DWM cloaked ข้ามไป |
| จอคนละ DPI | ขนาดเพี้ยน | ใช้ ratio + PER_MONITOR_AWARE_V2 |

---

## 10.1 วิธีเปิดแอพ (ตามที่ผู้ใช้ขอ)

**ไม่เปิดเองตอนบูต** — เป็นแอพใน Start menu กดเปิดเอง

| อยากได้ | ทำ |
|---|---|
| เปิด | Start → พิมพ์ `ScreenPin` (pin ไป taskbar ได้) |
| ปิดหน้าต่าง แต่ยังจัดจอให้ | กด X → ค้างใน tray |
| ปิดสนิท | tray → ออก · หรือ ตั้งค่า → ออกจากโปรแกรม |
| กด X = ปิดสนิท | ติ๊ก `close_quits` ในตั้งค่า |

**ปัญหาที่เจอ:** `WScript.Shell.CreateShortcut` (วิธีมาตรฐาน) แปลง path ภาษาไทย
เป็น `?` — และไดรฟ์ E: ไม่มี 8.3 short name ให้ใช้แทน
→ ต้องเรียก COM `IShellLinkW` + `IPersistFile` ตรงๆ ผ่าน ctypes (`shortcut.py`)

## 11. ผลวัดจริง (หลัง build)

| ตัววัด | ผล |
|---|---|
| engine tick (3 จอ, 7 หน้าต่าง) | **2.8 ms** |
| init แอพ | **78 ms** |
| ดึง state ผ่าน API | **1.6 ms** |
| dependency ที่ต้องลง | **0** |

**เทสที่ผ่าน (ใช้จอ/หน้าต่างจริง):**
- ปิดจอ → หน้าต่างถูกยัดไปจออื่น → เปิดจอกลับ → **คืนที่เดิมอัตโนมัติ**
- 2 หน้าต่างของ exe เดียวกันคนละจอ → **จำแยกกัน ไม่ทับกัน**
- อพยพก่อนปิดจอ → **ยังจำจอเดิม** → เปิดกลับมาคืนถูก
- self chain: จอหลัก → จอรอง → จอว่าง → จอหลักกลับมาเด้งกลับ (ผ่านทั้ง 4)
- global hotkey ย้ายหน้าต่างจริง + overlay picker กดเลขแล้วย้ายจริง

## 12. ลำดับ build

1. `win32.py` + `monitors.py` → ตรวจจอได้ + key ถูก
2. `windows.py` → list + ย้ายหน้าต่างได้
3. `config.py` + `engine.py` → chain resolve + auto restore
4. `msgloop.py` → hotkey + tray + display event
5. `ui.py` + `overlay.py` → หน้าจอ
6. launcher + README
