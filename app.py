from flask import Flask, render_template_string, jsonify, request, send_from_directory
import cv2 as cv
import os
import time
import requests
from datetime import datetime

app = Flask(__name__)

# =========================
# SERVER API
# =========================
SERVER_IMAGE_URL    = "https://geodev.fun/ucs/api/image/"
SERVER_CAPTURES_URL = "https://geodev.fun/ucs/api/captures"
SERVER_UPLOAD_URL   = "https://geodev.fun/ucs/api/upload"
SERVER_GPS_URL      = "https://geodev.fun/ucs/api/gps"

latest_capture = {}
latest_gps     = {"lat": None, "lng": None, "accuracy": None}

folder_name = "capture_images"
os.makedirs(folder_name, exist_ok=True)

cap1 = cv.VideoCapture(1, cv.CAP_DSHOW)
cap2 = cv.VideoCapture(2, cv.CAP_DSHOW)
cap1.set(cv.CAP_PROP_FRAME_WIDTH, 640)
cap1.set(cv.CAP_PROP_FRAME_HEIGHT, 480)
cap2.set(cv.CAP_PROP_FRAME_WIDTH, 640)
cap2.set(cv.CAP_PROP_FRAME_HEIGHT, 480)
print("Camera1:", cap1.isOpened())
print("Camera2:", cap2.isOpened())

capture_interval     = 5
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
body{font-family:Arial,sans-serif;background:#f0f2f5;padding-top:52px;}

/* TOP BAR */
.topbar{
    position:fixed;top:0;left:0;right:0;height:52px;
    background:#1a1a2e;display:flex;align-items:center;
    justify-content:space-between;padding:0 16px;
    z-index:9999;box-shadow:0 2px 8px rgba(0,0,0,.4);
}
.topbar-title{color:#00e5ff;font-size:15px;font-weight:bold;letter-spacing:2px;}
.cam-pills{display:flex;gap:10px;}
.cam-pill{
    display:flex;align-items:center;gap:6px;padding:5px 12px;
    border-radius:20px;font-size:12px;font-weight:bold;
    border:1px solid #444;color:#666;background:#111;transition:all .3s;
}
.cam-pill.on{border-color:#39ff6b;color:#39ff6b;background:rgba(57,255,107,.08);}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex-shrink:0;}
.dot.pulse{animation:blink 1.1s infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}

/* MAP */
#map{width:100%;height:280px;border-bottom:3px solid #00e5ff;}
.map-wrap{position:relative;}
.gps-box{
    position:absolute;bottom:10px;left:10px;z-index:500;
    background:rgba(0,0,0,.75);color:#00e5ff;font-size:11px;
    font-family:monospace;padding:5px 10px;border-radius:5px;
    border:1px solid #00e5ff;pointer-events:none;
}

/* CONTROLS */
.controls{
    background:#fff;padding:14px 20px;
    display:flex;align-items:center;gap:10px;flex-wrap:wrap;
    border-bottom:1px solid #ddd;
}
button{
    padding:12px 22px;font-size:15px;border:none;border-radius:6px;
    cursor:pointer;font-weight:bold;transition:transform .1s;
}
button:active{transform:scale(.97);}
button:disabled{opacity:.35;cursor:not-allowed;}
.btn-once {background:#2196F3;color:#fff;}
.btn-start{background:#4CAF50;color:#fff;}
.btn-stop {background:#f44336;color:#fff;}
.btn-cam  {background:#555;color:#fff;}
#status{margin-left:auto;font-size:13px;color:#555;font-style:italic;}

/* SECTION */
.section{margin:20px;}
.section h2{
    font-size:13px;letter-spacing:2px;text-transform:uppercase;
    color:#888;margin-bottom:14px;border-bottom:1px solid #ddd;
    padding-bottom:6px;display:flex;align-items:center;gap:8px;
}
.badge{
    background:#1a1a2e;color:#00e5ff;font-size:11px;
    padding:2px 8px;border-radius:10px;font-family:monospace;
}

/* ภาพกล้องตัวเอง */
.cam-row{display:flex;gap:16px;flex-wrap:wrap;}
.cam-card{
    background:#fff;padding:10px;border-radius:10px;
    box-shadow:0 2px 10px rgba(0,0,0,.1);width:320px;
}
.cam-card img{width:100%;border:2px solid #ddd;border-radius:6px;background:#eee;min-height:120px;}
.cam-label{font-weight:bold;font-size:13px;margin-bottom:6px;color:#333;}
.cam-meta{margin-top:8px;font-size:11px;color:#666;font-family:monospace;line-height:1.9;}

/* ── ตารางรายการไฟล์ ── */
.file-table{
    width:100%;border-collapse:collapse;background:#fff;
    border-radius:10px;overflow:hidden;
    box-shadow:0 2px 10px rgba(0,0,0,.08);
    font-size:13px;
}
.file-table thead{background:#1a1a2e;color:#00e5ff;}
.file-table thead th{
    padding:12px 14px;text-align:left;
    font-size:11px;letter-spacing:1px;font-weight:bold;
}
.file-table tbody tr{
    border-bottom:1px solid #f0f0f0;
    transition:background .15s;cursor:pointer;
}
.file-table tbody tr:hover{background:#f0faff;}
.file-table tbody tr:last-child{border-bottom:none;}
.file-table td{padding:10px 14px;vertical-align:middle;}
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
    padding:10px;background:#1a1a2e;color:#fff;
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
<div class="map-wrap">
    <div id="map"></div>
    <div class="gps-box" id="gps-box">📍 กำลังหาตำแหน่ง...</div>
</div>

<!-- CONTROLS -->
<div class="controls">
    <button class="btn-once"  onclick="manualCapture()">📷 ถ่ายครั้งเดียว</button>
    <button class="btn-start" id="btn-start" onclick="startAuto()">▶ เริ่มถ่าย</button>
    <button class="btn-stop"  id="btn-stop"  onclick="stopAuto()" disabled>⏹ หยุดถ่าย</button>
    <button class="btn-cam"   onclick="stopCamera()">🔴 ปิดกล้อง</button>
    <span id="status">พร้อมใช้งาน</span>
</div>

<!-- ภาพล่าสุด -->
<div class="section">
    <h2>ภาพล่าสุดจากกล้อง</h2>
    <div class="cam-row">
        <div class="cam-card">
            <div class="cam-label">📷 LEFT Camera</div>
            <img id="local1" src="" alt="ยังไม่มีภาพ">
            <div class="cam-meta" id="meta1">—</div>
        </div>
        <div class="cam-card">
            <div class="cam-label">📷 RIGHT Camera</div>
            <img id="local2" src="" alt="ยังไม่มีภาพ">
            <div class="cam-meta" id="meta2">—</div>
        </div>
    </div>
</div>

<!-- รายการไฟล์จาก DB -->
<div class="section">
    <h2>
        รายการภาพจาก Database
        <span class="badge" id="db-count">0 รายการ</span>
    </h2>
    <table class="file-table">
        <thead>
            <tr>
                <th>รูป</th>
                <th>ชื่อไฟล์</th>
                <th>กล้อง</th>
                <th>เวลา (UTC+7)</th>
                <th>พิกัด GPS</th>
            </tr>
        </thead>
        <tbody id="fileTableBody">
            <tr class="empty-row"><td colspan="5">กำลังโหลด...</td></tr>
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

async function manualCapture(){
    setStatus('กำลังถ่ายภาพ...');
    const res=await fetch('/capture',{method:'POST'});
    const data=await res.json();
    updateLocal(data);
    loadDB();
}

async function startAuto(){
    await fetch('/start_auto',{method:'POST'});
    setStatus('ถ่ายอัตโนมัติทุก 5 วิ...');
    document.getElementById('btn-start').disabled=true;
    document.getElementById('btn-stop').disabled=false;
    setCam(1,true); setCam(2,true);
    if(!autoTimer){
        autoTimer=setInterval(async()=>{
            await loadLatest();
            await loadDB();
        },5000);
    }
    const res = await fetch('/capture',{method:'POST'});
    const data = await res.json();
    updateLocal(data);
    loadDB();
}

async function stopAuto(){
    clearInterval(autoTimer); autoTimer=null;
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

// ─── โหลดตารางจาก DB ────────────────────────────
async function loadDB(){
    try{
        const res=await fetch('/server_captures');
        const list=await res.json();
        const tbody=document.getElementById('fileTableBody');

        if(!list||list.error||!list.length){
            tbody.innerHTML='<tr class="empty-row"><td colspan="5">ยังไม่มีข้อมูลใน database</td></tr>';
            document.getElementById('db-count').textContent='0 รายการ';
            return;
        }

        document.getElementById('db-count').textContent=list.length+' รายการ';

        tbody.innerHTML=list.map(item=>{
            const isLeft = item.device_id.includes('LEFT');
            const badge  = isLeft
                ? `<span class="device-badge left-badge">${item.device_id}</span>`
                : `<span class="device-badge right-badge">${item.device_id}</span>`;

            const gpsCell = (item.lat && item.lng)
                ? `<span class="gps-chip">📍 ${parseFloat(item.lat).toFixed(5)}, ${parseFloat(item.lng).toFixed(5)}</span>`
                : `<span class="no-gps-chip">ไม่มี GPS</span>`;

            const dataJson = encodeURIComponent(JSON.stringify(item));

            return `
            <tr onclick="openModal('${dataJson}')">
                <td><img class="file-thumb" src="${item.image_url}?t=${Date.now()}" loading="lazy"></td>
                <td style="font-family:monospace;font-size:12px;color:#555;">${item.filename}</td>
                <td>${badge}</td>
                <td style="font-family:monospace;font-size:12px;color:#555;white-space:nowrap;">${item.captured_at}</td>
                <td>${gpsCell}</td>
            </tr>`;
        }).join('');

    } catch(e){
        document.getElementById('fileTableBody').innerHTML=
            `<tr class="empty-row"><td colspan="5">⚠ โหลดไม่ได้: ${e.message}</td></tr>`;
    }
}

// ─── MODAL ──────────────────────────────────────
function openModal(dataJson){
    const item = JSON.parse(decodeURIComponent(dataJson));

    document.getElementById('modal-img').src      = item.image_url+'?t='+Date.now();
    document.getElementById('modal-filename').textContent = '📄 '+item.filename;
    document.getElementById('modal-time').textContent     = '🕐 '+item.captured_at;

    const isLeft = item.device_id.includes('LEFT');
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

def upload_image(filepath, device_id):
    lat = latest_gps.get("lat")
    lng = latest_gps.get("lng")
    acc = latest_gps.get("accuracy")
    try:
        with open(filepath, 'rb') as img:
            files = {'image': img}
            data  = {
                'device_id': device_id,
                'lat':      str(lat) if lat is not None else '',
                'lng':      str(lng) if lng is not None else '',
                'accuracy': str(acc) if acc is not None else '',
            }
            response = requests.post(SERVER_UPLOAD_URL, files=files, data=data, timeout=10)
        print(f"UPLOAD {device_id} | {response.status_code} | lat={lat} lng={lng}")
        print(f"  server: {response.text[:100]}")
    except Exception as e:
        print(f"UPLOAD ERROR {device_id}: {e}")


def save_images():
    global last_capture_time
    if not camera_running:
        return {"error": "Camera stopped"}
    for _ in range(3):
        cap1.read(); cap2.read()
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

    upload_image(path1, "CAM_LEFT")
    upload_image(path2, "CAM_RIGHT")

    last_capture_time = time.time()
    global latest_capture
    latest_capture = {
        "cap1": img1, "cap2": img2,
        "timestamp": timestamp,
        "lat": latest_gps.get("lat"),
        "lng": latest_gps.get("lng"),
    }
    return latest_capture

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

@app.route('/server_captures')
def server_captures():
    try:
        response = requests.get(SERVER_CAPTURES_URL, timeout=10)
        captures = response.json()
        results  = []
        for item in captures:
            results.append({
                "filename":    item["filename"],
                "device_id":   item["device_id"],
                "captured_at": item["captured_at"],
                "image_url":   SERVER_IMAGE_URL + item["filename"],
                "lat":         item.get("lat"),
                "lng":         item.get("lng"),
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)})

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
    import threading
    t = threading.Thread(target=auto_capture)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', debug=False, port=5000) #ssl_context='adhoc')