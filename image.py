import os
import re
import requests

BASE_URL = "https://geodev.fun"
LIMIT = 9999
OUTPUT = r"C:\GEO\image_499"
FOLDER = "2026-07-31-test"


def get_captures(limit: int = LIMIT):
    url = f"{BASE_URL}/ucs/api/captures/{limit}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()  # ต้องมี () ไม่งั้นไม่เช็ค error จริง
    return resp.json()


def download_image(image_url: str, save_path: str):
    resp = requests.get(image_url, timeout=30, stream=True)
    resp.raise_for_status()  # ต้องมี () ไม่งั้น error page จะถูกเซฟเป็น .jpg

    # เช็คว่า response เป็นรูปจริง ไม่ใช่ HTML error page
    content_type = resp.headers.get("Content-Type", "")
    if "image" not in content_type.lower():
        raise ValueError(f"ไม่ใช่ไฟล์ภาพ (Content-Type: {content_type})")

    tmp_path = save_path + ".part"
    with open(tmp_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    # เช็คว่าไฟล์ที่โหลดมามีขนาด > 0 ก่อน rename เป็นชื่อจริง
    if os.path.getsize(tmp_path) == 0:
        os.remove(tmp_path)
        raise ValueError("ไฟล์ที่ดาวน์โหลดมามีขนาด 0 byte")

    os.replace(tmp_path, save_path)


def safe_folder_name(name: str) -> str:
    name = (name or "unknown").strip()
    return re.sub(r'[<>:"/\\|?*]', "_", name) or "unknown"


def get_side(item: dict) -> str:
    """
    รองรับได้ทั้งกรณี API ใช้ key 'side' หรือ 'device_id'
    (เช่น device_id = 'CAM_LEFT' / 'CAM_RIGHT')
    """
    raw = item.get("side") or item.get("device_id") or "unknown"
    return safe_folder_name(str(raw).lower())


def main():
    print("กำลังดึงภาพจาก api")
    try:
        captures = get_captures()
    except Exception as e:
        print(f"⚠ ดึงรายการภาพจาก API ไม่สำเร็จ: {e}")
        return

    if not isinstance(captures, list):
        print(f"⚠ รูปแบบข้อมูลจาก API ไม่ถูกต้อง (ได้ {type(captures)}): {captures}")
        return

    print(f"พบภาพทั้งหมด {len(captures)} รายการ")

    success, skipped, failed = 0, 0, 0
    failed_items = []

    for item in captures:
        filename = item.get("filename")
        image_url = item.get("image_url")
        side = get_side(item)

        if not filename or not image_url:
            print(f"รายการที่ข้อมูลมาไม่ครบ: {item}")
            failed += 1
            failed_items.append(item)
            continue

        target_dir = os.path.join(OUTPUT, FOLDER, side)
        os.makedirs(target_dir, exist_ok=True)

        save_path = os.path.join(target_dir, filename)

        if os.path.exists(save_path):
            skipped += 1
            continue

        try:
            download_image(image_url, save_path)
            print(f"{filename} -> {target_dir}")
            success += 1

        except Exception as e:
            print(f"ดาวน์โหลดล้มเหลว: {filename} ({e})")
            failed += 1
            failed_items.append(item)

    print("\n===== สรุปผล =====")
    print(f"ดาวน์โหลดใหม่: {success}")
    print(f"มีอยู่แล้ว (ข้าม): {skipped}")
    print(f"ล้มเหลว: {failed}")
    print(f"รวม (success + skipped): {success + skipped} / API รายงานทั้งหมด: {len(captures)}")
    print(f"เก็บไฟล์ไว้ที่: {OUTPUT}")

    if failed_items:
        print("\n--- รายการที่ล้มเหลว ---")
        for it in failed_items:
            print(it)


if __name__ == "__main__":
    main()