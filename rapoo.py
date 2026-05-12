import cv2 as cv
import os
import time
from datetime import datetime


#สร้างที่เก็บรูปภาพ
folder_name = "capture_images"
os.makedirs(folder_name, exist_ok=True)

cap1 = cv.VideoCapture(1, cv.CAP_DSHOW)
cap2 = cv.VideoCapture(2, cv.CAP_DSHOW)

#ถ่ายภาพทุกๆ 5 วินาที
capture_interval = 5000  # 5000 milliseconds = 5 seconds
last_capture_time = time.time()


while True:

    ret1, frame1 = cap1.read()
    ret2, frame2 = cap2.read()

    if not ret1 or not ret2:
        print ("Failed")
        break

    cv.imshow("Cap1_Rapoo", frame1)
    cv.imshow("Cap2_Rapoo", frame2)

    current_time = time.time()

    def save_images():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        img_name1 = os.path.join(folder_name, f"cap1_{timestamp}.jpg")
        img_name2 = os.path.join(folder_name, f"cap2_{timestamp}.jpg")

        cv.imwrite(img_name1, frame1)
        cv.imwrite(img_name2, frame2)

        print(f"Saved: {img_name1}")
        print(f"Saved: {img_name2}")

    #Auto capture!

    if current_time - last_capture_time >= capture_interval / 1000:  # Convert milliseconds to seconds
        save_images()
        last_capture_time = current_time

    key = cv.waitKey(1) & 0xFF

    if key == 27:
        break

    if key == ord('s'):
        save_images()


cap1.release()
cap2.release()
cv.destroyAllWindows() 