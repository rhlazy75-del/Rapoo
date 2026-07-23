"""
════════════════════════════════════════════════════════════════
  สคริปต์ดึงภาพจาก Database ตามช่วงเวลาที่กำหนด
  - ดาวน์โหลดไฟล์ภาพเก็บไว้ในเครื่อง
  - บันทึกพิกัด GPS + กล้องข้างไหน (LEFT/RIGHT) ลงไฟล์ CSV

  วิธีใช้: แก้ค่าตรง "ส่วนที่ต้องแก้ทุกครั้ง" ด้านล่าง แล้วรัน
      python3 fetch_by_daterange.py
════════════════════════════════════════════════════════════════
"""
import os
import csv
import requests
from datetime import datetime, timedelta

# ══════════════════ ส่วนที่ต้องแก้ทุกครั้ง ══════════════════
# ระบุช่วงเวลาที่ต้องการดึง (เป็นเวลาไทย/เชียงใหม่ ตรงกับที่โชว์ในตารางบนเว็บ)
# รูปแบบ: "YYYY-MM-DD HH:MM:SS"
START_DATE = "2026-07-12 00:00:00"
END_DATE   = "2026-07-12 23:59:59"

# โฟลเดอร์ที่จะเก็บภาพที่ดาวน์โหลดมา (จะถูกสร้างอัตโนมัติถ้ายังไม่มี)
OUTPUT_FOLDER = "downloaded"

# กรองเฉพาะกล้องข้างใดข้างหนึ่งไหม ปล่อยเป็น None = เอาทั้งสองข้าง
# ใส่ "CAM_LEFT" หรือ "CAM_RIGHT" ถ้าต้องการกรองเฉพาะข้าง
FILTER_DEVICE_ID = None
# ══════════════════════════════════════════════════════════════

SERVER_CAPTURES_URL = "https://geodev.fun/ucs/api/captures"

# ประเทศไทย/เชียงใหม่ = UTC+7 คงที่ตลอดปี (ตรงกับที่ใช้ใน app.py หลัก)
CHIANGMAI_OFFSET = timedelta(hours=7)


def parse_server_time(ts_str):
    """แปลง captured_at ที่ได้จาก server (สมมติว่าเป็น UTC) ให้เป็นเวลาไทย"""
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt + CHIANGMAI_OFFSET
        except ValueError:
            continue
    return None


def main():
    start_dt = datetime.strptime(START_DATE, "%Y-%m-%d %H:%M:%S")
    end_dt   = datetime.strptime(END_DATE, "%Y-%m-%d %H:%M:%S")

    print(f"กำลังดึงรายการภาพทั้งหมดจาก {SERVER_CAPTURES_URL} ...")
    try:
        response = requests.get(SERVER_CAPTURES_URL, timeout=15)
        response.raise_for_status()
        captures = response.json()
    except Exception as e:
        print(f"❌ ดึงข้อมูลจาก server ไม่สำเร็จ: {e}")
        return

    if not isinstance(captures, list):
        print("❌ รูปแบบข้อมูลจาก server ไม่ถูกต้อง (ไม่ใช่ list)")
        return

    print(f"พบทั้งหมด {len(captures)} รายการใน database, กำลังกรองตามช่วงเวลา...")

    matched = []
    for item in captures:
        local_time = parse_server_time(item.get("captured_at", ""))
        if local_time is None:
            continue
        if not (start_dt <= local_time <= end_dt):
            continue
        if FILTER_DEVICE_ID and item.get("device_id") != FILTER_DEVICE_ID:
            continue
        matched.append((item, local_time))

    print(f"ตรงตามเงื่อนไข {len(matched)} รายการ (ช่วง {START_DATE} ถึง {END_DATE})")

    if not matched:
        print("ไม่มีภาพที่ตรงเงื่อนไข ไม่ต้องดาวน์โหลดอะไรเพิ่ม")
        return

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    csv_path = os.path.join(OUTPUT_FOLDER, "metadata.csv")

    downloaded = 0
    failed = []

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "filename", "captured_at_chiangmai", "device_id", "lat", "lng", "local_image_path"])

        for item, local_time in matched:
            filename  = item.get("filename")
            image_url = item.get("image_url")
            device_id = item.get("device_id")
            lat       = item.get("lat")
            lng       = item.get("lng")

            local_path = ""
            if image_url and filename:
                save_path = os.path.join(OUTPUT_FOLDER, filename)
                try:
                    img_res = requests.get(image_url, timeout=15)
                    img_res.raise_for_status()
                    with open(save_path, "wb") as img_f:
                        img_f.write(img_res.content)
                    downloaded += 1
                    local_path = save_path
                    print(f"  ✅ {filename}  ({device_id})  lat={lat} lng={lng}")
                except Exception as e:
                    failed.append(filename)
                    print(f"  ⚠️  ดาวน์โหลด {filename} ไม่สำเร็จ: {e}")
            else:
                failed.append(filename or "(ไม่มีชื่อไฟล์)")

            writer.writerow([
                item.get("id"),
                filename,
                local_time.strftime("%Y-%m-%d %H:%M:%S"),
                device_id,
                lat,
                lng,
                local_path,
            ])

    print()
    print(f"เสร็จสิ้น: ดาวน์โหลดสำเร็จ {downloaded}/{len(matched)} ภาพ")
    if failed:
        print(f"ไฟล์ที่ดาวน์โหลดไม่สำเร็จ: {failed}")
    print(f"ไฟล์ภาพเก็บไว้ที่โฟลเดอร์: {os.path.abspath(OUTPUT_FOLDER)}")
    print(f"ไฟล์ข้อมูล (พิกัด/กล้อง): {os.path.abspath(csv_path)}")


if __name__ == "__main__":
    main()