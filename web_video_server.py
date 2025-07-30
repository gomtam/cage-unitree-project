import cv2
import time
from flask import Flask, Response, render_template, request, jsonify
from multiprocessing import Queue
from webrtc_producer import start_webrtc, send_command, ensure_normal_mode_once
import threading
from ultralytics import YOLO  # YOLO 모델 임포트
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates')
frame_queue = Queue(maxsize=10)
command_queue = Queue(maxsize=10)
lidar_queue = Queue(maxsize=5)  # LiDAR 데이터 큐 추가

# YOLO 모델 로드
yolo_model = YOLO('project_CAGE/templates/yolo11n.pt')  # 모델 파일 경로


# WebRTC 프레임 수신 시작 (명령 큐와 LiDAR 큐도 전달)
start_webrtc(frame_queue, command_queue, lidar_queue)

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

@app.route('/lidar_data', methods=['GET'])
def lidar_data():
    """LiDAR 데이터를 JSON으로 반환"""
    if not lidar_queue.empty():
        try:
            data = lidar_queue.get_nowait()
            # LiDAR 데이터 구조 확인 및 변환
            response_data = {
                'point_count': data.get('point_count', 0),
                'positions': data.get('positions', []),
                'uvs': data.get('uvs', []),
                'indices': data.get('indices', []),
                'timestamp': time.time()
            }
            return jsonify(response_data)
        except Exception as e:
            logging.error(f"LiDAR data error: {e}")
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'point_count': 0, 'positions': [], 'timestamp': time.time()})

@app.route('/toggle_lidar', methods=['POST'])
def toggle_lidar():
    """LiDAR 센서 ON/OFF 토글"""
    data = request.get_json()
    lidar_state = data.get('state', 'on')  # 'on' 또는 'off'
    
    # 여기서는 단순히 상태를 반환하지만, 
    # 실제로는 webrtc_producer를 통해 LiDAR를 제어할 수 있습니다
    return jsonify({'status': 'ok', 'lidar_state': lidar_state})
    

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