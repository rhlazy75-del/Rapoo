from flask import Flask, render_template_string, jsonify, request, send_from_directory
import cv2 as cv
import os
import time
import requests
import threading
import queue
import json
from datetime import datetime

app = Flask(__name__)

# =========================
# SERVER API
# =========================
SERVER_IMAGE_URL    = "https://geodev.fun/ucs/api/image/"
SERVER_CAPTURES_BASE = "https://geodev.fun/ucs/api/captures"
SERVER_CAPTURES_URL = "https://geodev.fun/ucs/api/captures/20"
SERVER_UPLOAD_URL   = "https://geodev.fun/ucs/api/upload"
SERVER_GPS_URL      = "https://geodev.fun/ucs/api/gps"

# SERVER_IMAGE_URL    = "http://localhost:6601/ucs/api/image/"
# SERVER_CAPTURES_URL = "http://localhost:6601/ucs/api/captures"
# SERVER_UPLOAD_URL   = "http://localhost:6601/ucs/api/upload"
# SERVER_GPS_URL      = "http://localhost:6601/ucs/api/gps"

# จำนวนรายการล่าสุดที่จะแสดงในตาราง
DISPLAY_LIMIT = 20

latest_capture = {}
latest_gps     = {"lat": None, "lng": None, "accuracy": None}
capture_lock = threading.Lock()

folder_name = "capture_images"
os.makedirs(folder_name, exist_ok=True)

# ═══════ ส่วนควบคุมกล้อง ═══════
import subprocess

def v4l2_set(device, control, value):
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "-c", f"{control}={value}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[{device}] set {control}={value} FAIL: {result.stderr.strip()}")
    else:
        print(f"[{device}] set {control}={value} OK")

CAM1_DEVICE = "/dev/video0"
CAM2_DEVICE = "/dev/video2"

# กลางแจ้งให้ต่ำมาก ๆ ก่อน (ค่อยไล่เพิ่มทีหลัง)
EXPOSURE_VALUE = 5

# ═══════ ค่าคงที่อื่นๆ ของกล้อง (DEFAULT) ═══════
# ทุกครั้งที่เปิดโปรแกรมใหม่ (รัน python app.py ใหม่) กล้องจะถูกตั้งกลับมาเป็นค่าชุดนี้เสมอ
# ไม่ว่าก่อนปิดโปรแกรมจะเคยกด +/- ปรับไว้เท่าไหร่ก็ตาม (ไม่มีการบันทึกค่าลงไฟล์)
BRIGHTNESS_VALUE = 0
CONTRAST_VALUE   = 32
SATURATION_VALUE = 64
GAIN_VALUE       = 0
SHARPNESS_VALUE  = 3   # ยืนยันจาก v4l2-ctl -d /dev/video0 --list-ctrls : min=0 max=6 step=1 default=3

cap1 = cv.VideoCapture(CAM1_DEVICE, cv.CAP_V4L2)
cap1.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*'MJPG'))
cap1.set(cv.CAP_PROP_FRAME_WIDTH, 1280)
cap1.set(cv.CAP_PROP_FRAME_HEIGHT, 720)
cap1.set(cv.CAP_PROP_FPS, 5)
cap1.set(cv.CAP_PROP_BUFFERSIZE, 1)  #แก้ปัญหาภาพไม่เท่ากันในภาพ

cap2 = cv.VideoCapture(CAM2_DEVICE, cv.CAP_V4L2)
cap2.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*'MJPG'))
cap2.set(cv.CAP_PROP_FRAME_WIDTH, 1280)
cap2.set(cv.CAP_PROP_FRAME_HEIGHT, 720)
cap2.set(cv.CAP_PROP_FPS, 5)
cap2.set(cv.CAP_PROP_BUFFERSIZE, 1)  #แก้ปัญหาภาพไม่เท่ากันในภาพ

print("Camera1:", cap1.isOpened())
print("Camera2:", cap2.isOpened())

time.sleep(0.3)

# 2) ค่อยตั้งค่าด้วย v4l2 หลังเปิดกล้อง (กันค่าโดนรีเซ็ต)
def apply_settings(device, exp):
    v4l2_set(device, "exposure_auto", 1)
    v4l2_set(device, "exposure_auto_priority", 0)
    v4l2_set(device, "exposure_absolute", exp)

    # WB แนะนำให้ AUTO ก่อน จะเอาตัวรอดกลางแจ้งดีกว่า
    v4l2_set(device, "white_balance_temperature_auto", 1)

    # ลดความฟุ้ง
    v4l2_set(device, "brightness", BRIGHTNESS_VALUE)
    v4l2_set(device, "contrast", CONTRAST_VALUE)
    v4l2_set(device, "saturation", SATURATION_VALUE)
    v4l2_set(device, "gain", GAIN_VALUE)
    v4l2_set(device, "sharpness", SHARPNESS_VALUE)   # เพิ่ม: ทำให้ขอบภาพคมขึ้น

apply_settings(CAM1_DEVICE, EXPOSURE_VALUE)
apply_settings(CAM2_DEVICE, EXPOSURE_VALUE)

# 3) อ่านเฟรมทิ้งให้ค่ากล้องนิ่งก่อนเริ่มใช้งานจริง
for _ in range(10):
    cap1.read()
    cap2.read()

# ═══════ จบส่วนที่แทนที่ ═══════

# ─── ตัวแปรเก็บค่าปัจจุบันของกล้อง (อยู่ใน RAM เท่านั้น ไม่บันทึกลงไฟล์) ───
# เริ่มต้นเท่ากับค่าคงที่ด้านบนเสมอ พอปิดโปรแกรมแล้วเปิดใหม่ ตัวแปรนี้จะถูกสร้างใหม่
# และรีเซ็ตกลับมาเท่ากับค่าคงที่โดยอัตโนมัติ (ไม่มีการจำค่าที่เคยปรับไว้ข้ามรอบการรัน)
camera_state = {
    "exposure_absolute": EXPOSURE_VALUE,
    "brightness":         BRIGHTNESS_VALUE,
    "contrast":            CONTRAST_VALUE,
    "saturation":          SATURATION_VALUE,
    "gain":                GAIN_VALUE,
    "sharpness":           SHARPNESS_VALUE,
}

# ขอบเขตค่าที่อนุญาตให้ปรับ กันกด +/- จนเกินขอบที่กล้องรองรับ
# (เช็คค่าจริงของกล้องรุ่นที่ใช้ได้ด้วยคำสั่ง: v4l2-ctl -d /dev/video0 --list-ctrls)
CAMERA_LIMITS = {
    "exposure_absolute": (1, 5000),
    "brightness":         (-64, 64),
    "contrast":            (0, 64),
    "saturation":          (0, 128),
    "gain":                (0, 100),
    "sharpness":           (0, 6),      # ยืนยันแล้วจาก v4l2-ctl --list-ctrls ของกล้องจริง
}

CAMERA_STEP = {
    "exposure_absolute": 5,
    "brightness": 5,
    "contrast": 4,
    "saturation": 8,
    "gain": 5,
    "sharpness": 1,
}

def adjust_camera(control, direction):
    """direction: 1 = เพิ่ม, -1 = ลด. ปรับแค่ใน RAM (camera_state) ไม่บันทึกลงไฟล์ใดๆ
    ยิงคำสั่งไปที่กล้องทั้งสองตัวพร้อมกันเสมอด้วยค่าเดียวกัน"""
    if control not in camera_state or control not in CAMERA_LIMITS:
        return None, "ไม่รู้จัก control นี้"

    step = CAMERA_STEP[control]
    lo, hi = CAMERA_LIMITS[control]
    new_value = camera_state[control] + (step * direction)
    new_value = max(lo, min(hi, new_value))  # กันหลุดขอบเขต

    camera_state[control] = new_value
    for device in (CAM1_DEVICE, CAM2_DEVICE):   # ยิงไปทั้ง CAM1 และ CAM2 เสมอ
        v4l2_set(device, control, new_value)

    return new_value, None

def reset_camera_to_default():
    """สั่งกล้องทั้งสองตัวกลับไปเป็นค่าคงที่ (DEFAULT) ทันที โดยไม่ต้องรีสตาร์ทโปรแกรม"""
    global camera_state
    camera_state = {
        "exposure_absolute": EXPOSURE_VALUE,
        "brightness":         BRIGHTNESS_VALUE,
        "contrast":            CONTRAST_VALUE,
        "saturation":          SATURATION_VALUE,
        "gain":                GAIN_VALUE,
        "sharpness":           SHARPNESS_VALUE,
    }
    apply_settings(CAM1_DEVICE, EXPOSURE_VALUE)
    apply_settings(CAM2_DEVICE, EXPOSURE_VALUE)
    return camera_state

# ═══════ จบส่วนปรับค่ากล้อง +/- ═══════


# ═══════ ส่วนอัปโหลดขึ้น server แบบ queue + retry (กันภาพตกหล่น / กันอัปโหลดช้าเพราะยิงพร้อมกันหลาย thread) ═══════
UPLOAD_QUEUE_FILE  = "upload_queue.json"
UPLOAD_MAX_RETRIES = 30          # ลองส่งซ้ำได้สูงสุดกี่ครั้งก่อนยอมแพ้ (แล้ว log ไว้ใน failed_uploads.log)
UPLOAD_RETRY_DELAY = 10          # วินาที รอก่อน retry แต่ละครั้งที่ fail

upload_queue = queue.Queue()
upload_queue_lock = threading.Lock()

def load_pending_uploads():
    """ตอนเปิดโปรแกรมใหม่ โหลดรายการไฟล์ที่ยัง upload ไม่สำเร็จจากรอบก่อนกลับเข้า queue
    (กันกรณีปิดโปรแกรม/ไฟดับ/เน็ตหลุดตอนกำลังอัปโหลดค้างอยู่)"""
    if os.path.exists(UPLOAD_QUEUE_FILE):
        try:
            with open(UPLOAD_QUEUE_FILE, 'r') as f:
                pending = json.load(f)
            for item in pending:
                upload_queue.put(item)
            print(f"โหลด pending uploads ค้างจากรอบก่อน: {len(pending)} ไฟล์")
        except Exception as e:
            print(f"โหลด upload queue เดิมไม่ได้: {e}")

def save_pending_uploads():
    """เซฟสถานะ queue ปัจจุบันลงไฟล์ทุกครั้งที่มีการเปลี่ยนแปลง กันตกหล่นถ้าโปรแกรมถูกปิด/แครชกลางคัน"""
    with upload_queue_lock:
        items = list(upload_queue.queue)
    try:
        with open(UPLOAD_QUEUE_FILE, 'w') as f:
            json.dump(items, f)
    except Exception as e:
        print(f"เซฟ upload queue ไม่ได้: {e}")

def enqueue_upload(filepath, device_id, lat, lng, acc):
    """เพิ่มไฟล์เข้าคิวรออัปโหลด แทนที่จะยิง thread ทันทีแบบเดิม"""
    item = {
        "filepath": filepath,
        "device_id": device_id,
        "lat": lat, "lng": lng, "accuracy": acc,
        "retries": 0,
    }
    upload_queue.put(item)
    save_pending_uploads()

def upload_worker():
    """เธรดพื้นหลังตัวเดียว ทำงานตลอดชีวิตโปรแกรม ดึงไฟล์จาก queue ไปส่งทีละไฟล์
    - ทำทีละไฟล์ (ไม่ยิงพร้อมกันหลาย thread) กันเน็ต Pi โดนแย่ง bandwidth จนทุก request ช้า/timeout
    - ถ้า fail จะใส่กลับเข้า queue ใหม่และลองใหม่อัตโนมัติ ไม่ปล่อยให้ภาพหายเงียบๆ เหมือนเดิม
    """
    while True:
        item = upload_queue.get()
        filepath = item["filepath"]

        if not os.path.exists(filepath):
            print(f"[UPLOAD SKIP] ไฟล์หายไปแล้ว: {filepath}")
            upload_queue.task_done()
            save_pending_uploads()
            continue

        try:
            with open(filepath, 'rb') as img:
                files = {'image': img}
                data = {
                    'device_id': item["device_id"],
                    'lat':      str(item["lat"]) if item["lat"] is not None else '',
                    'lng':      str(item["lng"]) if item["lng"] is not None else '',
                    'accuracy': str(item["accuracy"]) if item["accuracy"] is not None else '',
                }
                response = requests.post(SERVER_UPLOAD_URL, files=files, data=data, timeout=20)

            if response.ok:
                print(f"[UPLOAD OK] {filepath} -> {item['device_id']} ({response.status_code})")
                upload_queue.task_done()
                save_pending_uploads()
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text[:100]}")

        except Exception as e:
            item["retries"] += 1
            print(f"[UPLOAD FAIL] {filepath} ครั้งที่ {item['retries']}: {e}")
            upload_queue.task_done()

            if item["retries"] >= UPLOAD_MAX_RETRIES:
                print(f"[UPLOAD GIVE UP] {filepath} ลองครบ {UPLOAD_MAX_RETRIES} ครั้งแล้วไม่สำเร็จ — บันทึกลง failed_uploads.log")
                try:
                    with open("failed_uploads.log", "a") as f:
                        f.write(f"{datetime.now()} | {filepath} | {item['device_id']} | {e}\n")
                except Exception:
                    pass
                save_pending_uploads()
            else:
                time.sleep(UPLOAD_RETRY_DELAY)
                upload_queue.put(item)
                save_pending_uploads()

def get_upload_queue_status():
    with upload_queue_lock:
        pending = len(upload_queue.queue)
    return {"pending": pending}

# ═══════ จบส่วนอัปโหลด queue + retry ═══════

capture_interval     = 5.0  # วินาที
last_capture_time    = time.time()
auto_capture_enabled = False
camera_running       = True

HTML = '''
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dual Camera Flask</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
    --navy:#12122b; --navy2:#1a1a3a; --cyan:#00e5ff; --cyan-dim:rgba(0,229,255,.12);
    --bg:#eef1f6; --card:#fff; --text:#233; --muted:#7a8296;
}
body{font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);padding-top:56px;color:var(--text);}

/* TOP BAR */
.topbar{
    position:fixed;top:0;left:0;right:0;height:56px;
    background:linear-gradient(120deg,var(--navy),var(--navy2));
    display:flex;align-items:center;
    justify-content:space-between;padding:0 18px;
    z-index:9999;box-shadow:0 2px 10px rgba(0,0,0,.35);
}
.topbar-title{color:var(--cyan);font-size:15px;font-weight:700;letter-spacing:2px;text-shadow:0 0 12px rgba(0,229,255,.35);}
.cam-pills{display:flex;gap:10px;}
.cam-pill{
    display:flex;align-items:center;gap:6px;padding:5px 12px;
    border-radius:20px;font-size:12px;font-weight:bold;
    border:1px solid #3a3a5c;color:#667;background:#0e0e22;transition:all .3s;
}
.cam-pill.on{border-color:#39ff6b;color:#39ff6b;background:rgba(57,255,107,.08);}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex-shrink:0;}
.dot.pulse{animation:blink 1.1s infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}

/* MAP */
.map-section{margin:20px;}
.map-label{
    font-size:13px;letter-spacing:2px;text-transform:uppercase;
    color:var(--muted);margin-bottom:10px;font-weight:700;
}
.map-wrap{position:relative;border-radius:12px;overflow:hidden;box-shadow:0 2px 14px rgba(0,0,0,.12);}
#map{width:100%;height:280px;}
.gps-box{
    position:absolute;bottom:10px;left:10px;z-index:500;
    background:rgba(10,10,25,.8);color:var(--cyan);font-size:11px;
    font-family:monospace;padding:5px 10px;border-radius:5px;
    border:1px solid var(--cyan);pointer-events:none;
}

/* CONTROLS - 4 ปุ่มตามผัง */
.controls{
    margin:20px;
    background:var(--card);padding:16px;border-radius:12px;
    display:flex;align-items:center;gap:12px;flex-wrap:wrap;
    box-shadow:0 2px 10px rgba(0,0,0,.06);
    border-left:4px solid var(--cyan);
}
button{
    padding:13px 20px;font-size:14px;border:none;border-radius:8px;
    cursor:pointer;font-weight:700;transition:transform .1s,filter .15s,box-shadow .15s;
    box-shadow:0 2px 6px rgba(0,0,0,.12);
}
button:hover{filter:brightness(1.06);box-shadow:0 4px 10px rgba(0,0,0,.18);}
button:active{transform:scale(.97);}
button:disabled{opacity:.35;cursor:not-allowed;}
.btn-once  {background:#2196F3;color:#fff;}
.btn-start {background:#4CAF50;color:#fff;}
.btn-stop  {background:#f44336;color:#fff;}
.btn-wipe  {background:#7c1fa2;color:#fff;}
.btn-cam   {background:#555;color:#fff;}
.btn-delete{background:#ff5252;color:#fff;padding:8px 12px;font-size:12px;border-radius:6px;}
#status{margin-left:auto;font-size:13px;color:var(--muted);font-style:italic;}

/* ADJUST PANEL — แถบปุ่ม +/- ปรับค่ากล้อง */
.adjust-section{
    margin:20px;background:var(--card);padding:16px;border-radius:12px;
    box-shadow:0 2px 10px rgba(0,0,0,.06);
    border-left:4px solid #ff9800;
}
.adjust-head{
    display:flex;align-items:center;justify-content:space-between;
    margin-bottom:14px;flex-wrap:wrap;gap:8px;
}
.adjust-title{
    font-size:13px;letter-spacing:1px;text-transform:uppercase;
    color:var(--muted);font-weight:700;
}
.btn-reset{background:#e65100;color:#fff;font-size:12px;padding:8px 14px;}
.adjust-row{
    display:flex;align-items:center;gap:12px;
    padding:8px 0;border-bottom:1px solid #f0f0f0;
}
.adjust-row:last-child{border-bottom:none;}
.adjust-label{width:150px;font-size:13px;color:var(--text);font-weight:700;}
.adjust-btn{
    width:38px;height:38px;padding:0;font-size:20px;
    background:var(--navy);color:var(--cyan);border-radius:8px;
}
.adjust-value{
    min-width:60px;text-align:center;font-family:monospace;
    font-size:15px;font-weight:700;color:var(--text);
    background:#f0f2f6;padding:6px 10px;border-radius:6px;
}
.adjust-default{
    font-size:11px;color:var(--muted);font-family:monospace;
}

/* UPLOAD STATUS PANEL */
.upload-status-section{
    margin:20px;background:var(--card);padding:14px 16px;border-radius:12px;
    box-shadow:0 2px 10px rgba(0,0,0,.06);
    border-left:4px solid #00c853;
    display:flex;align-items:center;gap:14px;flex-wrap:wrap;
}
.upload-status-title{
    font-size:13px;letter-spacing:1px;text-transform:uppercase;
    color:var(--muted);font-weight:700;
}
.upload-pending-badge{
    background:var(--navy);color:#39ff6b;font-size:13px;
    padding:5px 12px;border-radius:10px;font-family:monospace;font-weight:700;
}
.upload-pending-badge.has-pending{color:#ffb300;}

/* SECTION */
.section{margin:20px;}
.section h2{
    font-size:13px;letter-spacing:2px;text-transform:uppercase;
    color:var(--muted);margin-bottom:14px;border-bottom:1px solid #dfe3ea;
    padding-bottom:8px;display:flex;align-items:center;gap:8px;font-weight:700;
}
.badge{
    background:var(--navy);color:var(--cyan);font-size:11px;
    padding:3px 9px;border-radius:10px;font-family:monospace;font-weight:700;
}

/* กล้อง LEFT / RIGHT */
.cam-row{display:flex;gap:16px;flex-wrap:wrap;}
.cam-card{
    background:var(--card);padding:0;border-radius:12px;overflow:hidden;
    box-shadow:0 2px 12px rgba(0,0,0,.1);width:340px;
    border-top:3px solid var(--cyan);transition:box-shadow .2s,transform .2s;
}
.cam-card:hover{box-shadow:0 6px 20px rgba(0,0,0,.14);transform:translateY(-2px);}
.cam-card-head{
    background:var(--navy);color:var(--cyan);font-weight:700;
    font-size:14px;padding:10px 14px;letter-spacing:.5px;
}
.cam-card-body{padding:10px;}
.cam-card img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:6px;background:#dfe3ea;}
.cam-meta{margin-top:8px;font-size:11px;color:var(--muted);font-family:monospace;line-height:1.9;}

/* ── ตารางรายการไฟล์ ── */
.file-table{
    width:100%;border-collapse:collapse;background:var(--card);
    border-radius:12px;overflow:hidden;
    box-shadow:0 2px 10px rgba(0,0,0,.08);
    font-size:13px;
}
.file-table thead{background:var(--navy);color:var(--cyan);}
.file-table thead th{
    padding:12px 14px;text-align:left;
    font-size:11px;letter-spacing:1px;font-weight:700;
}
.file-table tbody tr{
    border-bottom:1px solid #f0f0f0;
    transition:background .15s,box-shadow .15s;cursor:pointer;
}
.file-table tbody tr:hover{background:var(--cyan-dim);box-shadow:inset 3px 0 0 var(--cyan);}
.file-table tbody tr:last-child{border-bottom:none;}
.file-table td{padding:10px 14px;vertical-align:middle;}
.id-chip{
    display:inline-block;min-width:26px;text-align:center;
    background:#eef1f6;color:#556;border-radius:5px;
    padding:3px 7px;font-family:monospace;font-size:12px;font-weight:700;
}
.file-thumb{
    width:56px;height:40px;object-fit:cover;
    border-radius:4px;border:1px solid #ddd;background:#eee;
}
.gps-chip{
    display:inline-block;background:#fff8f0;
    border:1px solid #ffe0b2;color:#e65100;
    border-radius:4px;padding:2px 7px;font-size:11px;
    font-family:monospace;
}
.no-gps-chip{
    display:inline-block;background:#f5f5f5;
    border:1px solid #ddd;color:#bbb;
    border-radius:4px;padding:2px 7px;font-size:11px;
}
.device-badge{
    font-weight:bold;font-size:11px;letter-spacing:1px;
    padding:2px 8px;border-radius:4px;
}
.left-badge {background:#e3f2fd;color:#1565c0;}
.right-badge{background:#f3e5f5;color:#6a1b9a;}

/* ── MODAL ── */
.modal-overlay{
    display:none;position:fixed;inset:0;z-index:10000;
    background:rgba(0,0,0,.75);
    justify-content:center;align-items:center;
}
.modal-overlay.show{display:flex;}
.modal-box{
    background:#fff;border-radius:14px;
    max-width:600px;width:94%;
    box-shadow:0 10px 40px rgba(0,0,0,.4);
    overflow:hidden;animation:popIn .2s ease;
}
@keyframes popIn{from{transform:scale(.9);opacity:0}to{transform:scale(1);opacity:1}}
.modal-img{width:100%;max-height:360px;object-fit:contain;background:#111;display:block;}
.modal-body{padding:16px;}
.modal-filename{
    font-family:monospace;font-size:13px;
    color:#333;margin-bottom:10px;word-break:break-all;
}
.modal-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;align-items:center;}
.modal-gps{
    background:#fff8f0;border:1px solid #ffe0b2;
    border-radius:6px;padding:8px 12px;font-family:monospace;
    font-size:12px;color:#e65100;flex:1;
}
.modal-gps.no{background:#f5f5f5;border-color:#ddd;color:#aaa;}
.modal-time{font-size:12px;color:#888;font-family:monospace;}
.modal-close{
    display:block;width:100%;margin-top:12px;
    padding:10px;background:var(--navy);color:#fff;
    border:none;border-radius:6px;cursor:pointer;font-size:14px;
}
.modal-close:hover{background:#2a2a4e;}
.modal-map-link{
    display:inline-block;margin-top:6px;font-size:12px;
    color:#1565c0;text-decoration:none;font-family:monospace;
}
.modal-map-link:hover{text-decoration:underline;}

.empty-row td{text-align:center;color:#bbb;font-style:italic;padding:40px;}
</style>
</head>
<body>

<!-- TOP BAR -->
<div class="topbar">
    <div class="topbar-title">📷 Rapoo C200</div>
    <div class="cam-pills">
        <div class="cam-pill" id="pill1"><div class="dot" id="dot1"></div>LEFT</div>
        <div class="cam-pill" id="pill2"><div class="dot" id="dot2"></div>RIGHT</div>
    </div>
</div>

<!-- MAP -->
<div class="map-section">
    <div class="map-label">MAP</div>
    <div class="map-wrap">
        <div id="map"></div>
        <div class="gps-box" id="gps-box">📍 กำลังหาตำแหน่ง...</div>
    </div>
</div>

<!-- CONTROLS: ปุ่มหลัก -->
<div class="controls">
    <button class="btn-once"  onclick="manualCapture()">📷 ปุ่มสั่งถ่ายภาพครั้งเดียว</button>
    <button class="btn-start" id="btn-start" onclick="startAuto()">▶ ปุ่มสั่งถ่ายภาพแบบ loop</button>
    <button class="btn-stop"  id="btn-stop"  onclick="stopAuto()" disabled>⏹ ปุ่มสั่งหยุดถ่ายภาพแบบ loop</button>
    <button class="btn-wipe"  onclick="deleteAllCaptures()">🗑️ ลบรูปทั้งหมดใน Database</button>
    <button class="btn-cam"   onclick="stopCamera()">🔴 ปิดกล้อง</button>
    <span id="status">พร้อมใช้งาน</span>
</div>

<!-- ═══ สถานะคิวอัปโหลดขึ้น server ═══ -->
<div class="upload-status-section">
    <span class="upload-status-title">☁️ สถานะอัปโหลดขึ้น Server</span>
    <span class="upload-pending-badge" id="upload-pending-badge">รอส่ง: 0</span>
    <span id="upload-status-note" style="font-size:12px;color:var(--muted);">
        ภาพที่ถ่ายจะเข้าคิวส่งอัตโนมัติ ถ้าส่งไม่สำเร็จจะลองใหม่เองจนกว่าจะสำเร็จ
    </span>
</div>

<!-- ═══ แถบปรับค่ากล้อง +/- ═══ -->
<div class="adjust-section">
    <div class="adjust-head">
        <span class="adjust-title">⚙️ ปรับค่ากล้อง (ชั่วคราว — รีเซ็ตกลับค่าเดิมทุกครั้งที่เปิดโปรแกรมใหม่ / ปรับพร้อมกันทั้ง 2 กล้อง)</span>
        <button class="btn-reset" onclick="resetCamera()">↺ รีเซ็ตเป็นค่าเดิมตอนนี้เลย</button>
    </div>

    <div class="adjust-row" data-control="exposure_absolute">
        <span class="adjust-label">Exposure (แสง)</span>
        <button class="adjust-btn" onclick="adjustCam('exposure_absolute','down')">−</button>
        <span class="adjust-value" id="val-exposure_absolute">5</span>
        <button class="adjust-btn" onclick="adjustCam('exposure_absolute','up')">+</button>
        <span class="adjust-default">(ค่าเดิมในโค้ด: 5)</span>
    </div>

    <div class="adjust-row" data-control="brightness">
        <span class="adjust-label">Brightness (สว่าง)</span>
        <button class="adjust-btn" onclick="adjustCam('brightness','down')">−</button>
        <span class="adjust-value" id="val-brightness">0</span>
        <button class="adjust-btn" onclick="adjustCam('brightness','up')">+</button>
        <span class="adjust-default">(ค่าเดิมในโค้ด: 0)</span>
    </div>

    <div class="adjust-row" data-control="contrast">
        <span class="adjust-label">Contrast (คมชัด)</span>
        <button class="adjust-btn" onclick="adjustCam('contrast','down')">−</button>
        <span class="adjust-value" id="val-contrast">32</span>
        <button class="adjust-btn" onclick="adjustCam('contrast','up')">+</button>
        <span class="adjust-default">(ค่าเดิมในโค้ด: 32)</span>
    </div>

    <div class="adjust-row" data-control="saturation">
        <span class="adjust-label">Saturation (อิ่มสี)</span>
        <button class="adjust-btn" onclick="adjustCam('saturation','down')">−</button>
        <span class="adjust-value" id="val-saturation">64</span>
        <button class="adjust-btn" onclick="adjustCam('saturation','up')">+</button>
        <span class="adjust-default">(ค่าเดิมในโค้ด: 64)</span>
    </div>

    <div class="adjust-row" data-control="gain">
        <span class="adjust-label">Gain (ชดเชยแสงน้อย)</span>
        <button class="adjust-btn" onclick="adjustCam('gain','down')">−</button>
        <span class="adjust-value" id="val-gain">0</span>
        <button class="adjust-btn" onclick="adjustCam('gain','up')">+</button>
        <span class="adjust-default">(ค่าเดิมในโค้ด: 0)</span>
    </div>

    <div class="adjust-row" data-control="sharpness">
        <span class="adjust-label">Sharpness (คมชัด)</span>
        <button class="adjust-btn" onclick="adjustCam('sharpness','down')">−</button>
        <span class="adjust-value" id="val-sharpness">3</span>
        <button class="adjust-btn" onclick="adjustCam('sharpness','up')">+</button>
        <span class="adjust-default">(ค่าเดิมในโค้ด: 3, ช่วง 0-6)</span>
    </div>
</div>

<!-- ภาพล่าสุด -->
<div class="section">
    <h2>ภาพล่าสุดจากกล้อง</h2>
    <div class="cam-row">
        <div class="cam-card">
            <div class="cam-card-head">left camera</div>
            <div class="cam-card-body">
                <img id="local1" src="" alt="ยังไม่มีภาพ">
                <div class="cam-meta" id="meta1">—</div>
            </div>
        </div>
        <div class="cam-card">
            <div class="cam-card-head">right camera</div>
            <div class="cam-card-body">
                <img id="local2" src="" alt="ยังไม่มีภาพ">
                <div class="cam-meta" id="meta2">—</div>
            </div>
        </div>
    </div>
</div>

<!-- รายการไฟล์จาก DB -->
<div class="section">
    <h2>
        แสดงข้อมูลใน database 50 ภาพล่าสุด
        <span class="badge" id="db-count">ทั้งหมดใน DB: 0</span>
    </h2>
    <table class="file-table">
        <thead>
            <tr>
                <th>ID :</th>
                <th>IMG :</th>
                <th>NAME :</th>
                <th>CAM :</th>
                <th>TIME (เชียงใหม่) :</th>
                <th>GPS :</th>
                <th>DELETE :</th>
            </tr>
        </thead>
        <tbody id="fileTableBody">
            <tr class="empty-row"><td colspan="7">กำลังโหลด...</td></tr>
        </tbody>
    </table>
</div>

<!-- MODAL popup -->
<div class="modal-overlay" id="modal" onclick="closeModal(event)">
    <div class="modal-box">
        <img class="modal-img" id="modal-img" src="" alt="">
        <div class="modal-body">
            <div class="modal-filename" id="modal-filename"></div>
            <div class="modal-row">
                <div class="modal-time" id="modal-time"></div>
                <span id="modal-device"></span>
            </div>
            <div id="modal-gps" class="modal-gps no">ไม่มีข้อมูล GPS</div>
            <a id="modal-map-link" class="modal-map-link" href="#" target="_blank"
               style="display:none">🗺 เปิดใน Google Maps</a>
            <button class="modal-close" onclick="closeModalBtn()">✕ ปิด</button>
        </div>
    </div>
</div>

<script>
// ─── GPS ────────────────────────────────────────
let currentLat = null, currentLng = null, currentAcc = null;
let map = null, mapMarker = null;

function initMap(lat, lng){
    if(map){ map.setView([lat,lng],16); return; }
    map = L.map('map',{zoomControl:true,attributionControl:false}).setView([lat,lng],16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);
    const icon = L.divIcon({
        className:'',
        html:`<div style="width:14px;height:14px;background:#00e5ff;border-radius:50%;
              border:3px solid #fff;box-shadow:0 0 12px #00e5ff"></div>`,
        iconSize:[14,14], iconAnchor:[7,7]
    });
    mapMarker = L.marker([lat,lng],{icon}).addTo(map);
}

function onGPS(pos){
    currentLat = pos.coords.latitude;
    currentLng = pos.coords.longitude;
    currentAcc = pos.coords.accuracy;
    document.getElementById('gps-box').textContent =
        '📍 ' + currentLat.toFixed(6) + ', ' + currentLng.toFixed(6) +
        '  ±' + Math.round(currentAcc) + 'm';
    initMap(currentLat, currentLng);
    if(mapMarker) mapMarker.setLatLng([currentLat, currentLng]);
    fetch('/update_gps',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({lat:currentLat, lng:currentLng, accuracy:currentAcc})
    }).catch(()=>{});
}

if(navigator.geolocation){
    navigator.geolocation.watchPosition(onGPS,
        ()=>{ document.getElementById('gps-box').textContent='⚠ ไม่สามารถรับ GPS'; },
        {enableHighAccuracy:true, maximumAge:5000, timeout:10000});
} else {
    document.getElementById('gps-box').textContent='⚠ ไม่รองรับ GPS';
}

// ─── CAM STATUS ─────────────────────────────────
function setCam(n,on){
    const pill = document.getElementById('pill'+n);
    if(!pill) return;
    pill.classList.toggle('on',on);
    const d = document.getElementById('dot'+n);
    if(!d) return;
    if(on) d.classList.add('pulse'); else d.classList.remove('pulse');
}

// ─── CAPTURE ────────────────────────────────────
let autoTimer=null;
let wakelock=null; // ป้องกันมือถือหลับหน้าจอเวลาเปิดถ่ายอัตโนมัติ

async function requestWakeLock(){
    try{
        if('wakeLock' in navigator){
            wakelock = await navigator.wakeLock.request('screen');
            console.log('Wake Lock acquired');
        }
    }catch(err){console.error('Wake Lock error:', err);}
}
function releaseWakeLock(){
    if(wakelock){ wakelock.release(); wakelock=null; }
}
document.addEventListener('visibilitychange', ()=>{
    if(autoTimer && document.visibilityState === 'visible'){
        requestWakeLock();
    }
});

async function manualCapture(){
    setStatus('กำลังถ่ายภาพ...');
    const res=await fetch('/capture',{method:'POST'});
    const data=await res.json();
    updateLocal(data);
    loadDB();
    loadUploadStatus();
}

async function startAuto(){
    await fetch('/start_auto',{method:'POST'});
    await requestWakeLock();
    setStatus('ถ่ายอัตโนมัติทุก 5 วิ...');
    document.getElementById('btn-start').disabled=true;
    document.getElementById('btn-stop').disabled=false;
    setCam(1,true); setCam(2,true);
    if(!autoTimer){
        autoTimer=setInterval(async()=>{
            await loadLatest();
            await loadDB();
            await loadUploadStatus();
        },5000);
    }
    const res = await fetch('/capture',{method:'POST'});
    const data = await res.json();
    updateLocal(data);
    loadDB();
    loadUploadStatus();
}

async function stopAuto(){
    clearInterval(autoTimer); autoTimer=null;
    releaseWakeLock();
    await fetch('/stop_auto',{method:'POST'});
    setStatus('หยุดถ่ายภาพแล้ว');
    document.getElementById('btn-start').disabled=false;
    document.getElementById('btn-stop').disabled=true;
    setCam(1,false); setCam(2,false);   
}

async function stopCamera(){
    const res=await fetch('/stop_camera',{method:'POST'});
    const data=await res.json();
    setStatus(data.message);
    setCam(1,false); setCam(2,false);
    releaseWakeLock();
}

async function loadLatest(){
    const res=await fetch('/latest');
    const data=await res.json();
    if(data.cap1) updateLocal(data);
}

function updateLocal(data){
    if(data.error){ setStatus('⚠ '+data.error); return; }
    setStatus('ถ่ายสำเร็จ: '+data.timestamp);
    setCam(1,true); setCam(2,true);
    const t='?t='+Date.now();
    const local1 = document.getElementById('local1');
    const local2 = document.getElementById('local2');
    if(local1) local1.src='/capture_images/'+data.cap1+t;
    if(local2) local2.src='/capture_images/'+data.cap2+t;
    const gpsText=(data.lat&&data.lng)
        ?`📍 ${parseFloat(data.lat).toFixed(6)}, ${parseFloat(data.lng).toFixed(6)}`
        :'📍 ไม่มีข้อมูล GPS';
    const meta1 = document.getElementById('meta1');
    const meta2 = document.getElementById('meta2');
    if(meta1) meta1.innerHTML=`เวลา: ${data.timestamp}<br>${gpsText}`;
    if(meta2) meta2.innerHTML=`เวลา: ${data.timestamp}<br>${gpsText}`;
}

// ─── ปรับค่ากล้อง +/- ───────────────────────────
async function adjustCam(control, direction){
    const res = await fetch(`/adjust/${control}/${direction}`, {method:'POST'});
    const data = await res.json();
    if(data.error){ setStatus('⚠ '+data.error); return; }
    document.getElementById('val-'+control).textContent = data.value;
    setStatus(`ปรับ ${control} = ${data.value} (ทั้ง 2 กล้อง)`);
}

async function resetCamera(){
    if(!confirm('รีเซ็ตค่ากล้องกลับเป็นค่าเดิมในโค้ดตอนนี้เลยหรือไม่? (จะปรับทั้ง 2 กล้อง)')) return;
    setStatus('กำลังรีเซ็ตค่ากล้อง...');
    const res = await fetch('/reset_camera', {method:'POST'});
    const data = await res.json();
    for(const [control, value] of Object.entries(data.state)){
        const el = document.getElementById('val-'+control);
        if(el) el.textContent = value;
    }
    setStatus('รีเซ็ตค่ากล้องเรียบร้อยแล้ว (ทั้ง 2 กล้อง)');
}

async function loadCameraState(){
    try{
        const res = await fetch('/camera_state');
        const state = await res.json();
        for(const [control, value] of Object.entries(state)){
            const el = document.getElementById('val-'+control);
            if(el) el.textContent = value;
        }
    }catch(e){
        console.error('โหลดค่ากล้องไม่ได้', e);
    }
}
loadCameraState();  // ดึงค่าปัจจุบันจาก backend มาโชว์ตอนเปิดหน้าเว็บ

// ─── สถานะคิวอัปโหลด ──────────────────────────
async function loadUploadStatus(){
    try{
        const res = await fetch('/upload_status');
        const data = await res.json();
        const badge = document.getElementById('upload-pending-badge');
        badge.textContent = 'รอส่ง: ' + data.pending;
        badge.classList.toggle('has-pending', data.pending > 0);
    }catch(e){
        console.error('โหลดสถานะ upload ไม่ได้', e);
    }
}
loadUploadStatus();
setInterval(loadUploadStatus, 4000); // เช็คสถานะคิวอัปโหลดทุก 4 วิ ไม่ต้องรอ auto capture

// ─── โหลดตารางจาก DB (ล่าสุด 50 ภาพ) ────────────
async function loadDB(){
    try{
        const res=await fetch('/server_captures');
        const payload=await res.json();

        const tbody=document.getElementById('fileTableBody');

        if(!payload || payload.error){
            tbody.innerHTML=`<tr class="empty-row"><td colspan="7">⚠ โหลดไม่ได้: ${payload && payload.error ? payload.error : 'unknown error'}</td></tr>`;
            document.getElementById('db-count').textContent='ทั้งหมดใน DB: 0';
            return;
        }

        const list  = payload.items || [];
        const total = payload.total ?? list.length;

        document.getElementById('db-count').textContent = 'ทั้งหมดใน DB: ' + total;

        if(!list.length){
            tbody.innerHTML='<tr class="empty-row"><td colspan="7">ยังไม่มีข้อมูลใน database</td></tr>';
            return;
        }

        tbody.innerHTML=list.map(item=>{
            const isLeft = (item.device_id || '').includes('LEFT');
            const badge  = isLeft
                ? `<span class="device-badge left-badge">${item.device_id}</span>`
                : `<span class="device-badge right-badge">${item.device_id}</span>`;

            const gpsCell = (item.lat && item.lng)
                ? `<span class="gps-chip">📍 ${parseFloat(item.lat).toFixed(5)}, ${parseFloat(item.lng).toFixed(5)}</span>`
                : `<span class="no-gps-chip">ไม่มี GPS</span>`;

            const dataJson = encodeURIComponent(JSON.stringify(item));
            const fileArg  = encodeURIComponent(item.filename);

            return `
            <tr onclick="openModal('${dataJson}')">
                <td><span class="id-chip">${item.id}</span></td>
                <td><img class="file-thumb" src="${item.image_url}?t=${Date.now()}" loading="lazy"></td>
                <td style="font-family:monospace;font-size:12px;color:#555;">${item.filename}</td>
                <td>${badge}</td>
                <td style="font-family:monospace;font-size:12px;color:#555;white-space:nowrap;">${item.captured_at}</td>
                <td>${gpsCell}</td>
                <td style="white-space:nowrap;text-align:center;">
                    <button class="btn-delete" onclick="event.stopPropagation(); deleteCapture('${fileArg}')">🗑️ ลบ</button>
                </td>
            </tr>`;
        }).join('');

    } catch(e){
        document.getElementById('fileTableBody').innerHTML=
            `<tr class="empty-row"><td colspan="7">⚠ โหลดไม่ได้: ${e.message}</td></tr>`;
    }
}

async function deleteCapture(filename){
    if(!filename) return;
    const decoded = decodeURIComponent(filename);
    if(!confirm(`ยืนยันลบไฟล์ ${decoded} ?`)) return;
    setStatus('กำลังลบ '+decoded+'...');
    try{
        const res = await fetch(`/delete_capture/${filename}`, {method:'DELETE'});
        const data = await res.json();
        if(!res.ok || data.error){
            throw new Error(data.error || `HTTP ${res.status}`);
        }
        setStatus('ลบสำเร็จ: '+decoded);
        await loadDB();
    } catch(err){
        setStatus('⚠ ไม่สามารถลบได้: '+err.message);
    }
}

// ─── ลบรูปทั้งหมดใน Database (มีแจ้งเตือนก่อนลบอยู่แล้ว) ─────
async function deleteAllCaptures(){
    if(!confirm('⚠️ คำเตือน: นี่คือฐานข้อมูลกลางที่ใช้ร่วมกับอุปกรณ์/กล้องอื่นด้วย\\n\\nการกดยืนยันจะลบรูปภาพ "ทั้งหมดในระบบ" ทุกอุปกรณ์ ไม่ใช่แค่ของเครื่องนี้ และไม่สามารถย้อนกลับได้\\n\\nยืนยันลบทั้งหมดใช่หรือไม่?')) return;
    setStatus('กำลังลบข้อมูลทั้งหมดใน database...');
    try{
        const res = await fetch('/delete_all_captures', {method:'DELETE'});
        const data = await res.json();
        if(!res.ok || data.error){
            throw new Error(data.error || `HTTP ${res.status}`);
        }
        setStatus(`ลบข้อมูลทั้งหมดสำเร็จ (${data.deleted}/${data.total} รายการ)`);
        await loadDB();
    } catch(err){
        setStatus('⚠ ไม่สามารถลบทั้งหมดได้: '+err.message);
    }
}

// ─── MODAL ──────────────────────────────────────
function openModal(dataJson){
    const item = JSON.parse(decodeURIComponent(dataJson));

    document.getElementById('modal-img').src      = item.image_url+'?t='+Date.now();
    document.getElementById('modal-filename').textContent = '📄 '+item.filename;
    document.getElementById('modal-time').textContent     = '🕐 '+item.captured_at;

    const isLeft = (item.device_id || '').includes('LEFT');
    document.getElementById('modal-device').innerHTML = isLeft
        ? `<span class="device-badge left-badge">${item.device_id}</span>`
        : `<span class="device-badge right-badge">${item.device_id}</span>`;

    const gpsDiv  = document.getElementById('modal-gps');
    const mapLink = document.getElementById('modal-map-link');

    if(item.lat && item.lng){
        const lat = parseFloat(item.lat).toFixed(6);
        const lng = parseFloat(item.lng).toFixed(6);
        gpsDiv.className='modal-gps';
        gpsDiv.innerHTML=`📍 Lat: <b>${lat}</b><br>&nbsp;&nbsp;&nbsp;Lng: <b>${lng}</b>`;
        mapLink.style.display='inline-block';
        mapLink.href=`https://www.google.com/maps?q=${lat},${lng}`;
    } else {
        gpsDiv.className='modal-gps no';
        gpsDiv.textContent='ไม่มีข้อมูล GPS';
        mapLink.style.display='none';
    }

    document.getElementById('modal').classList.add('show');
}

function closeModal(e){
    if(e.target===document.getElementById('modal')) closeModalBtn();
}
function closeModalBtn(){
    document.getElementById('modal').classList.remove('show');
    document.getElementById('modal-img').src='';
}

function setStatus(msg){ document.getElementById('status').textContent=msg; }

loadDB();
</script>
</body>
</html>
'''

def save_images():
    global last_capture_time
    if not camera_running:
        return {"error": "Camera stopped"}
    if not capture_lock.acquire(blocking=False):
        return {"error": "Capture in progress"}
    try:
        for _ in range(3):  # ลองอ่านภาพ 3 ครั้ง ถ้า fail จะ retry
            cap1.read(); cap2.read()
            time.sleep(0.03)
        ret1, frame1 = cap1.read()
        ret2, frame2 = cap2.read()

        if not ret1: return {"error": "Camera 1 failed"}
        if not ret2: return {"error": "Camera 2 failed"}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        img1  = f"cap1_{timestamp}.jpg"
        img2  = f"cap2_{timestamp}.jpg"
        path1 = os.path.join(folder_name, img1)
        path2 = os.path.join(folder_name, img2)
        cv.imwrite(path1, frame1)
        cv.imwrite(path2, frame2)
        print(f"Saved: {path1}, {path2}")

        # เข้าคิวอัปโหลดแทนการยิง thread ลอยๆ แบบเดิม
        # (worker เดียวทำทีละไฟล์ + retry อัตโนมัติ กันภาพหายและกันอัปโหลดช้าเพราะแย่ง bandwidth)
        enqueue_upload(path1, "CAM_LEFT",  latest_gps.get("lat"), latest_gps.get("lng"), latest_gps.get("accuracy"))
        enqueue_upload(path2, "CAM_RIGHT", latest_gps.get("lat"), latest_gps.get("lng"), latest_gps.get("accuracy"))

        last_capture_time = time.time()
        global latest_capture
        latest_capture = {
            "cap1": img1, "cap2": img2,
            "timestamp": timestamp,
            "lat": latest_gps.get("lat"),
            "lng": latest_gps.get("lng"),
        }
        return latest_capture
    finally:
        capture_lock.release()
    

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/capture', methods=['POST'])
def capture():
    return jsonify(save_images())

@app.route('/latest')
def latest():
    return jsonify(latest_capture)

@app.route('/start_auto', methods=['POST'])
def start_auto():
    global auto_capture_enabled, last_capture_time
    auto_capture_enabled = True
    last_capture_time = 0
    print('AUTO CAPTURE ENABLED')
    return jsonify({"message": "เริ่มถ่ายภาพอัตโนมัติแล้ว"})

@app.route('/stop_auto', methods=['POST'])
def stop_auto():
    global auto_capture_enabled
    auto_capture_enabled = False
    return jsonify({"message": "หยุดถ่ายภาพแล้ว"})

@app.route('/stop_camera', methods=['POST'])
def stop_camera():
    global camera_running
    camera_running = False
    cap1.release(); cap2.release()
    return jsonify({"message": "ปิดกล้องแล้ว"})

@app.route('/update_gps', methods=['POST'])
def update_gps():
    global latest_gps
    body = request.get_json(force=True, silent=True) or {}
    lat  = body.get('lat')
    lng  = body.get('lng')
    acc  = body.get('accuracy')
    if lat is not None and lng is not None:
        latest_gps = {"lat": lat, "lng": lng, "accuracy": acc}
        print(f"GPS: {lat:.6f}, {lng:.6f} ±{acc}m")
        try:
            requests.post(SERVER_GPS_URL,
                json={"lat": lat, "lng": lng, "accuracy": acc, "device": "MOBILE"},
                timeout=5)
        except Exception:
            pass
    return jsonify({"ok": True})

# ═══════ ROUTES ปรับค่ากล้อง (+/-) ═══════

@app.route('/adjust/<control>/<direction>', methods=['POST'])
def adjust_route(control, direction):
    if direction not in ("up", "down"):
        return jsonify({"error": "direction ต้องเป็น up หรือ down"}), 400
    d = 1 if direction == "up" else -1
    new_value, err = adjust_camera(control, d)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"control": control, "value": new_value})

@app.route('/reset_camera', methods=['POST'])
def reset_camera_route():
    state = reset_camera_to_default()
    return jsonify({"message": "รีเซ็ตค่ากล้องเป็นค่าเดิมแล้ว (ทั้ง 2 กล้อง)", "state": state})

@app.route('/camera_state')
def get_camera_state():
    return jsonify(camera_state)

# ═══════ จบ ROUTES ปรับค่ากล้อง ═══════

# ═══════ ROUTE สถานะคิวอัปโหลด ═══════
@app.route('/upload_status')
def upload_status_route():
    return jsonify(get_upload_queue_status())
# ═══════ จบ ROUTE สถานะคิวอัปโหลด ═══════

@app.route('/server_captures')
def server_captures():
    """
    ดึงรายการภาพทั้งหมดจาก server แล้วส่งกลับเป็น:
      {
        "total": <จำนวนภาพทั้งหมดใน database>,
        "items": [ ...ล่าสุด 50 รายการ... ]   # เรียงใหม่สุดก่อน พร้อมเลข id
      }
    """
    try:
        response = requests.get(SERVER_CAPTURES_URL, timeout= 5)
        captures = response.json()

        if not isinstance(captures, list):
            return jsonify({"error": "รูปแบบข้อมูลจาก server ไม่ถูกต้อง"})

        total = len(captures)

        # เรียงตามเวลาถ่ายล่าสุดก่อน ถ้ามี captured_at ให้ sort, ไม่งั้นถือว่า list เรียงมาแล้ว
        try:
            captures_sorted = sorted(
                captures, key=lambda x: x.get("captured_at", ""), reverse=True
            )
        except Exception:
            captures_sorted = list(reversed(captures))

        latest_items = captures_sorted[:DISPLAY_LIMIT]

        results = []
        for idx, item in enumerate(latest_items):
            # ถ้า server ไม่ได้ส่งฟิลด์ id มาด้วย ให้คำนวณเลขลำดับสำรอง
            # โดยนับจากตำแหน่งจริงในชุดข้อมูลทั้งหมด (ใหม่สุด = total, เก่าสุด = 1)
            # กันไม่ให้ตาราง id column โชว์ "None"
            item_id = item.get("id")
            if item_id is None:
                item_id = total - idx

            results.append({
                "id":          item_id,
                "filename":    item["filename"],
                "device_id":   item["device_id"],
                "captured_at": (item["captured_at"]),
                "image_url":   item.get("image_url") or (SERVER_IMAGE_URL + item["filename"]),
                "lat":         item.get("lat"),
                "lng":         item.get("lng"),
            })

        return jsonify({"total": total, "items": results})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/delete_capture/<path:filename>', methods=['DELETE'])
def delete_capture(filename):
    try:
        target_url = f"{SERVER_CAPTURES_BASE}/{filename}"
        response = requests.delete(target_url, timeout=10)
        if response.ok:
            return jsonify({"ok": True, "status_code": response.status_code})
        return jsonify({"error": response.text or 'Delete failed', "status_code": response.status_code}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/delete_all_captures', methods=['DELETE'])
def delete_all_captures():
    try:
        target_url = f"{SERVER_CAPTURES_BASE}"
        response = requests.delete(target_url, timeout=10)
        if response.ok:
            return jsonify({"ok": True, "status_code": response.status_code})
        return jsonify({"error": response.text or 'Delete failed', "status_code": response.status_code}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/capture_images/<filename>')
def images(filename):
    return send_from_directory(folder_name, filename)

def auto_capture():
    global last_capture_time
    while True:
        try:
            if auto_capture_enabled and camera_running:
                if time.time() - last_capture_time >= capture_interval:
                    print("AUTO CAPTURE")
                    print(save_images())
            time.sleep(1)
        except Exception as e:
            print("AUTO LOOP ERROR:", e)
            time.sleep(1)

if __name__ == '__main__':
    load_pending_uploads()                # โหลดไฟล์ที่ยัง upload ไม่สำเร็จจากรอบก่อน (ถ้ามี)

    t_upload = threading.Thread(target=upload_worker)  # worker อัปโหลดพื้นหลัง (ทีละไฟล์ + retry)
    t_upload.daemon = True
    t_upload.start()

    t = threading.Thread(target=auto_capture)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', debug=False, port=5000)