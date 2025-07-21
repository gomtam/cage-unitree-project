import cv2
import time
from flask import Flask, Response, render_template, request, jsonify
from multiprocessing import Queue
from go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection, WebRTCConnectionMethod
from project_CAGE.webrtc_producer import start_webrtc, send_command, ensure_normal_mode_once
import threading
from ultralytics import YOLO  # YOLO 모델 임포트

from dotenv import load_dotenv
import os

# .env 파일 로드
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

SERIAL_NUMBER = os.getenv("SERIAL_NUMBER")
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")

app = Flask(__name__, template_folder='templates')
frame_queue = Queue(maxsize=10)
command_queue = Queue(maxsize=10)

# YOLO 모델 로드
yolo_model = YOLO('project_CAGE/templates/yolo11n.pt')  # 모델 파일 경로

# Go2WebRTCConnection 객체 생성
'''
conn = Go2WebRTCConnection(
    WebRTCConnectionMethod.Remote,
    serialNumber=SERIAL_NUMBER,
    username=USERNAME,
    password=PASSWORD
)
'''
# WebRTC 프레임 수신 시작 (명령 큐도 전달)
start_webrtc(frame_queue, command_queue)

def generate():
    last_detect_time = 0
    last_boxes = []
    while True:
        if not frame_queue.empty():
            img = frame_queue.get()
            now = time.time()
            # 1초에 한 번만 YOLO 추론
            if now - last_detect_time > 1.0:
                results = yolo_model(img)
                last_boxes = []
                for result in results:
                    boxes = result.boxes
                    for box in boxes:
                        cls = int(box.cls[0])
                        label = yolo_model.names[cls]
                        if label == "person":
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            last_boxes.append((x1, y1, x2, y2))
                last_detect_time = now
            # 이전 결과(박스)만 영상에 표시
            for (x1, y1, x2, y2) in last_boxes:
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(img, "person", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)
            ret, jpeg = cv2.imencode('.jpg', img)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        else:
            time.sleep(0.01)

@app.route('/video_feed')
def video_feed():
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/move', methods=['POST'])
def move():
    data = request.get_json()
    direction = data.get('direction')
    send_command(command_queue, direction)
    return jsonify({'status': 'ok', 'direction': direction})

@app.route('/joystick', methods=['POST'])
def joystick():
    data = request.get_json()
    x = float(data.get('x', 0))
    z = float(data.get('z', 0))
    send_command(command_queue, ('joystick', x, z))
    return jsonify({'status': 'ok'})

@app.route('/start_control', methods=['POST'])
def start_control():
    ok = ensure_normal_mode_once()
    return jsonify({'status': 'ok' if ok else 'fail'})
    

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5010, debug=False)


'''
@misc{lin2015microsoft,
      title={Microsoft COCO: Common Objects in Context},
      author={Tsung-Yi Lin and Michael Maire and Serge Belongie and Lubomir Bourdev and Ross Girshick and James Hays and Pietro Perona and Deva Ramanan and C. Lawrence Zitnick and Piotr Dollár},
      year={2015},
      eprint={1405.0312},
      archivePrefix={arXiv},
      primaryClass={cs.CV}
}
'''