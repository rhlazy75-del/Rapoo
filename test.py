import cv2 as cv

for i in range(5):
    cap = cv.VideoCapture(i, cv.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        print(f"index {i} → isOpened=True | read={ret}")
        cap.release()
    else:
        print(f"index {i} → ไม่มีกล้อง")