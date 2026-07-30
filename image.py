import os
import re 
import requests

BASE_URL = "https://geodev.fun"
LIMIT = 9999
OUTPUT = r"C:\GEO\image_499"
FOLDER = "2026-07-30"

def get_captures(limit: int = LIMIT):
    url = f"{BASE_URL}/ucs/api/captures/{limit}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status
    return resp.json()

def download_image(image_url: str, save_path: str):
    resp = requests.get(image_url, timeout=30, stream=True)
    resp.raise_for_status
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

def safe_folder_name(name: str) -> str:
    name = (name or "unknow").strip()
    return re.sub(r'[<>:"/\\|?*]', "_", name) or "unknow"

def main():
    print("กำลังดึงภาพจาก api")
    captures = get_captures()
    print(f"พบภาพทั้งหมด {len(captures)} รายการ")

    success, skipped, failed = 0, 0, 0

    for item in captures:
        filename = item.get("filename")
        image_url = item.get("image_url")
        side = safe_folder_name((item.get("side") or "unknown").lower())

        if not filename or not image_url:
            print(f"รายการที่ข้อมูลมาไม่ครบ: {item}")
            failed += 1
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

    print("\n===== สรุปผล =====")
    print(f"ดาวน์โหลดใหม่: {success}")
    print(f"มีอยู่แล้ว (ข้าม): {skipped}")
    print(f"ล้มเหลว: {failed}")
    print(f"เก็บไฟล์ไว้ที่: {OUTPUT}")
 
if __name__ == "__main__":
    main()