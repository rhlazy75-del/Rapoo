import cv2 as cv

for i in range(5):
    cap = cv.VideoCapture(i, cv.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        print(f"index {i} → isOpened=True | read={ret}")
        cap.release()
    else:
        print(f"index {i} → ไม่มีกล้อง")

# import cv2

# cap = cv2.VideoCapture(1)

# while True:
#     ret, frame = cap.read()
#     if not ret:
#         break

#     cv2.imshow("Rapoo Camera", frame)

#     if cv2.waitKey(1) & 0xFF == ord('q'):
#         break

# cap.release()
# cv2.destroyAllWindows()