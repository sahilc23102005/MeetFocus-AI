
import cv2
import mediapipe as mp
import time

model_path = "blaze_face_short_range.tflite"

BaseOptions = mp.tasks.BaseOptions
FaceDetector = mp.tasks.vision.FaceDetector
VisionRunningMode = mp.tasks.vision.RunningMode

options = mp.tasks.vision.FaceDetectorOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.VIDEO,
    min_detection_confidence=0.5
)

camera = cv2.VideoCapture(0)

with FaceDetector.create_from_options(options) as detector:
    while camera.isOpened():
        success, frame = camera.read()

        if not success:
            print("Camera not found!")
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame
        )

        timestamp_ms = int(time.time() * 1000)
        result = detector.detect_for_video(mp_image, timestamp_ms)

        for detection in result.detections:
            box = detection.bounding_box
            x, y = box.origin_x, box.origin_y
            w, h = box.width, box.height

            cv2.rectangle(
                frame, (x, y), (x + w, y + h), (0, 255, 0), 2
            )

            cv2.putText(
                frame, "Face Detected", (x, max(30, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
            )

        cv2.imshow("MeetFocus AI - Face Detection", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

camera.release()
cv2.destroyAllWindows()
