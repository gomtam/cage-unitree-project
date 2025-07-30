import asyncio
import threading
import time
import logging
import json
import av
from multiprocessing import Queue
from go2_webrtc_connect.go2_webrtc_driver.webrtc_driver import Go2WebRTCConnection, WebRTCConnectionMethod
from go2_webrtc_connect.go2_webrtc_driver.constants import RTC_TOPIC, SPORT_CMD
from aiortc import MediaStreamTrack


# 디버깅 
import os
from pathlib import Path
print("=== 환경 디버깅 ===")
print(f"현재 작업 디렉터리: {os.getcwd()}")
print(f"스크립트 위치: {__file__}")
print(f"프로젝트 루트: {Path(__file__).parent}")
# 디버깅


from config.settings import SERIAL_NUMBER, UNITREE_USERNAME, UNITREE_PASSWORD

# 디버깅
print("=== 환경변수 확인 ===")
print(f"SERIAL_NUMBER: {SERIAL_NUMBER}")
print(f"UNITREE_USERNAME: {UNITREE_USERNAME}")
print(f"UNITREE_PASSWORD: {'설정됨' if UNITREE_PASSWORD else 'None'}")
# 디버깅

logging.basicConfig(level=logging.FATAL)
logging.basicConfig(level=logging.INFO)

_conn_holder = {}

# 최신 조이스틱 값만 저장 (sitdown/situp 등은 큐 사용)
latest_joystick = None
# LiDAR 큐를 위한 전역 변수
global_lidar_queue = None

def start_webrtc(frame_queue, command_queue, lidar_queue=None):
    global global_lidar_queue
    global_lidar_queue = lidar_queue  # 전역 변수에 할당
    # av.logging.set_level(av.logging.ERROR) 
    av.logging.set_level(av.logging.DEBUG) # 로깅을 디버그 레벨로 변경

    async def recv_camera_stream(track: MediaStreamTrack):
        while True:
            try:
                frame = await track.recv()
                img = frame.to_ndarray(format="bgr24")
                frame_queue.put(img)
            except Exception as e:
                logging.error(f"Frame decode error: {e}")

    async def recv_lidar_data(conn):
        """LiDAR 데이터 수신 및 처리"""
        if global_lidar_queue is None:
            return
            
        try:
            # LiDAR 센서 활성화
            print("[LiDAR] LiDAR 센서를 활성화합니다...")
            await conn.datachannel.disableTrafficSaving(True)
            conn.datachannel.set_decoder(decoder_type='libvoxel')  # 복셀 디코더 사용
            conn.datachannel.pub_sub.publish_without_callback("rt/utlidar/switch", "on")
            
            def lidar_callback(message):
                """LiDAR 데이터 콜백 함수"""
                try:
                    lidar_data = message.get("data", {})
                    if lidar_data:
                        # 포인트 클라우드 데이터를 큐에 추가
                        if not global_lidar_queue.full():
                            global_lidar_queue.put(lidar_data)
                        else:
                            # 큐가 가득 찬 경우 오래된 데이터 제거
                            try:
                                global_lidar_queue.get_nowait()
                                global_lidar_queue.put(lidar_data)
                            except:
                                pass
                except Exception as e:
                    logging.error(f"LiDAR callback error: {e}")
            
            # LiDAR 복셀 맵 데이터 구독
            conn.datachannel.pub_sub.subscribe("rt/utlidar/voxel_map_compressed", lidar_callback)
            print("[LiDAR] LiDAR 데이터 구독을 시작했습니다.")
            
        except Exception as e:
            logging.error(f"LiDAR setup error: {e}")

    async def _ensure_normal_mode(conn):
        try:
            response = await conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001}
            )
            if response['data']['header']['status']['code'] == 0:
                data = json.loads(response['data']['data'])
                current_motion_switcher_mode = data['name']
                print(f"[모드 확인] 현재 모드: {current_motion_switcher_mode}")
            else:
                print("[모드 확인] 현재 모드 조회 실패")

            if current_motion_switcher_mode != "normal":
                print(f"[모드 전환] {current_motion_switcher_mode} → normal 모드로 변경 시도")
                
                # 모드 전환 최대 3회 시도
                for attempt in range(3):
                    print(f"[모드 전환] 시도 {attempt + 1}/3")
                    # 더 강력한 모드 전환 명령 시도
                    response2 = await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["MOTION_SWITCHER"],
                        {"api_id": 1002, "parameter": {"name": "normal"}}
                    )
                    
                    # 추가적인 강제 모드 전환 시도
                    await asyncio.sleep(2)
                    response2_force = await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["MOTION_SWITCHER"],
                        {"api_id": 1002, "parameter": {"name": "normal", "force": True}}
                    )
                    print(f"[모드 전환] 강제 전환 명령 응답: {response2_force}")
                    print(f"[모드 전환] 전환 명령 응답: {response2}")
                    
                    await asyncio.sleep(10)  # 대기 시간을 10초로 늘림
                    
                    # 모드 확인
                    response3 = await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001}
                    )
                    if response3['data']['header']['status']['code'] == 0:
                        data = json.loads(response3['data']['data'])
                        current_mode = data['name']
                        print(f"[모드 확인] 시도 {attempt + 1} 후 모드: {current_mode}")
                        
                        if current_mode == "normal":
                            print("✅ [모드 전환] Normal 모드 전환 성공!")
                            break
                        else:
                            print(f"❌ [모드 전환] 여전히 {current_mode} 모드")
                    else:
                        print("[모드 확인] 변경 후 모드 조회 실패")
                        
                    if attempt < 2:  # 마지막 시도가 아니면
                        print("[모드 전환] 5초 후 재시도...")
                        await asyncio.sleep(5)
                else:
                    print("🚨 [모드 전환] 3회 시도 후에도 Normal 모드 전환 실패!")
                    print("🔧 [해결책] Unitree 앱에서 '개발자 모드' 또는 '고급 설정'을 확인하세요.")
        except Exception as e:
            print(f"[모드 확인] 에러 발생: {e}")

    async def handle_command(conn):
        global latest_joystick
        while True:
            # sitdown/situp 등은 큐에서 처리
            if not command_queue.empty():
                direction = command_queue.get()
                if direction == "sitdown":
                    print("Performing 'StandDown' movement...")
                    await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["SPORT_MOD"],
                        {"api_id": SPORT_CMD["StandDown"]}
                    )
                elif direction == "situp":
                    print("Performing 'StandUp' movement...")
                    await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["SPORT_MOD"],
                        {"api_id": SPORT_CMD["StandUp"]}
                    )
                    print("Performing 'BalanceStand' movement...")
                    await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["SPORT_MOD"],
                        {"api_id": SPORT_CMD["BalanceStand"]}
                    )
                # 기타 명령은 필요시 추가
            # 최신 조이스틱 값만 사용
            if latest_joystick is not None:
                _, x, z = latest_joystick
                print(f"Joystick command (latest): x={x}, z={z}")
                response = await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {"api_id": SPORT_CMD["Move"], "parameter": {"x": float(x), "y": 0, "z": float(z)}}
                )
                print("Move response:", response)
            await asyncio.sleep(0.1)  # 50ms마다 최신 값 전송

    async def main_webrtc():
        conn = Go2WebRTCConnection(
            WebRTCConnectionMethod.Remote,
            serialNumber=SERIAL_NUMBER,
            username=UNITREE_USERNAME,
            password=UNITREE_PASSWORD
        )
        await conn.connect()
        
        # 전역 연결 참조 저장
        _conn_holder['conn'] = conn
        
        conn.video.switchVideoChannel(True)
        conn.video.add_track_callback(recv_camera_stream)
        await _ensure_normal_mode(conn)
        
        # 비동기 작업들 시작
        asyncio.create_task(handle_command(conn))
        asyncio.create_task(recv_lidar_data(conn))
        
        # 루프가 살아있도록 대기
        while True:
            await asyncio.sleep(1)

    # 메인 루프를 별도 스레드에서 실행
    def run_loop():
        asyncio.run(main_webrtc())

    threading.Thread(target=run_loop, daemon=True).start()

# 외부에서 명령을 큐에 넣는 함수
def send_command(command_queue, direction):
    global latest_joystick
    if isinstance(direction, tuple) and direction[0] == 'joystick':
        latest_joystick = direction  # 최신 값으로 덮어쓰기
    else:
        command_queue.put(direction)  # sitdown, situp 등은 기존 큐 사용

# 외부에서 normal 모드 전환을 요청할 때 호출
def ensure_normal_mode_once():
    import asyncio
    conn = _conn_holder.get('conn')
    if conn is None:
        print("No connection yet.")
        return False
    async def switch():
        await asyncio.sleep(1)  # 연결이 완전히 될 때까지 잠깐 대기
        await conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001}
        )
        response = await conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001}
        )
        current_motion_switcher_mode = "normal"
        if response['data']['header']['status']['code'] == 0:
            data = json.loads(response['data']['data'])
            current_motion_switcher_mode = data['name']
        if current_motion_switcher_mode != "normal":
            await conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["MOTION_SWITCHER"],
                {"api_id": 1002, "parameter": {"name": "normal"}}
            )
            await asyncio.sleep(10)
    threading.Thread(target=lambda: asyncio.run(switch()), daemon=True).start()
    return True

if __name__ == "__main__":
    frame_queue = Queue(maxsize=10)
    command_queue = Queue(maxsize=10)
    lidar_queue = Queue(maxsize=5)  # LiDAR 데이터는 용량이 클 수 있으므로 작은 큐 사용
    start_webrtc(frame_queue, command_queue, lidar_queue)

    # 예시: 키보드 입력으로 명령 전달
    while True:
        if not frame_queue.empty():
            img = frame_queue.get()
            print(f"Frame: {img.shape}")
        
        if not lidar_queue.empty():
            lidar_data = lidar_queue.get()
            print(f"LiDAR: point_count={lidar_data.get('point_count', 0)}")
        
        time.sleep(0.01)
        direction = input("Enter direction (sitdown/situp): ")
        send_command(command_queue, direction)
