import sys
import time
import json
import queue
import threading
import alsaaudio
import pymumble_py3 as pymumble
import math
import struct

# =========================================================================
# 🔥 파이썬 3.12 이상 최신 SSL 표준 및 구형 Murmur 서버 호환 패치
# =========================================================================
import ssl
if not hasattr(ssl, 'wrap_socket'):
    def legacy_wrap_socket(sock, *args, **kwargs):
        kwargs.pop('ssl_version', None)
        certfile = kwargs.pop('certfile', None)
        keyfile = kwargs.pop('keyfile', None)
        
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) 
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        
        if certfile:
            context.load_cert_chain(certfile, keyfile)
        return context.wrap_socket(sock, *args, **kwargs)
        
    ssl.wrap_socket = legacy_wrap_socket
# =========================================================================

# 스레드 간 오디오 버퍼 공유 큐
audio_queue = queue.Queue(maxsize=150)
running = True

# JSON 설정 데이터 글로벌 변수
config = {}


def mumble_sender_thread(mumble_instance):
    """ 연산 부하를 최적화하고 데이터 크기를 모니터링하는 송출 스레드 """
    global running
    print("[+] [Sender] Mumble 송출 스레드가 시작되었습니다.")
    
    sound_handler = None
    if hasattr(mumble_instance, "sound_wrapper"):
        sound_handler = mumble_instance.sound_wrapper
    elif hasattr(mumble_instance, "sound_output"):
        sound_handler = mumble_instance.sound_output
    else:
        for attr in dir(mumble_instance):
            if "sound" in attr.lower() and hasattr(getattr(mumble_instance, attr), "add_sound"):
                sound_handler = getattr(mumble_instance, attr)
                break

    if sound_handler is None:
        print("[-] [Sender] 크리티컬: 오디오 송출 모듈을 찾을 수 없습니다.")
        running = False
        return

    BAR_MAX_WIDTH = 55  

    while running:
        try:
            data = audio_queue.get(block=True, timeout=1.0)
            data_len = len(data)
            
            if data_len > 0:
                count = data_len // 2
                shorts = struct.unpack(f"{count}h", data)
                
                sum_squares = sum(shorts[i] ** 2 for i in range(0, count, 10))
                sampled_count = count // 10
                
                rms = math.sqrt(sum_squares / sampled_count) if sampled_count > 0 else 0
                normalized_rms = min(rms / 32768.0, 1.0)
                
                if sys.stdout.isatty():
                    bar_length = int(normalized_rms * BAR_MAX_WIDTH)
                    meter_bar = "█" * bar_length + " " * (BAR_MAX_WIDTH - bar_length)
                
                sys.stdout.write(f"\r[AUDIO] |{meter_bar}| [{normalized_rms * 100:5.1f}%] [{data_len}B]")
                sys.stdout.flush()

            if mumble_instance.is_alive():
                sound_handler.add_sound(data)
            audio_queue.task_done()
            
        except queue.Empty:
            continue
        except Exception as e:
            print(f"\n[-] [Sender] 에러 발생: {e}", file=sys.stderr)
            break
            
    print("\n[-] [Sender] Mumble 송출 스레드가 종료되었습니다.")


def audio_capture_thread():
    """ ALSA에서 설정된 장치 이름(예: hw:2,0)으로 직접 캡처 후 모노 다운믹싱 """
    global running
    
    # config에서 alsa_device 설정을 가져옴 (없으면 옛날 값 0 기준 기본 장치 설정)
    device_setting = config.get('alsa_device', 'default')
    
    # 만약 기존의 숫자 형태(예: 0, 2)나 숫자로 된 문자열이 들어왔을 경우 하위 호환 처리
    if isinstance(device_setting, int) or (isinstance(device_setting, str) and device_setting.isdigit()):
        device_name = f"hw:{device_setting},0"
    else:
        device_name = str(device_setting)

    print(f"[+] [Capture] ALSA 장치 직접 연결을 시도합니다... (Device: '{device_name}')")

    try:
        # cardindex 대신 device 인자값에 'hw:0,0' 이나 'hw:2,0' 문자열을 직접 주입합니다.
        inp = alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            channels=config['channels'],
            rate=config['sample_rate'],
            format=alsaaudio.PCM_FORMAT_S16_LE,
            periodsize=config['chunk_size'],
            device=device_name
        )
    except Exception as e:
        print(f"[-] [Capture] ALSA 하드웨어 오픈 실패 ('{device_name}'): {e}")
        running = False
        return

    print(f"[+] [Capture] 오디오 캡처 스레드 가동 시작 (Device: '{device_name}' / 스테레오 -> 모노 다운믹싱).")
    TARGET_SIZE = 1920

    while running:
        try:
            length, data = inp.read()
            if length > 0 and data:
                total_samples = len(data) // 2
                stereo_shorts = struct.unpack(f"{total_samples}h", data)
                
                mono_shorts = []
                for i in range(0, total_samples, 2):
                    left = stereo_shorts[i]
                    right = stereo_shorts[i+1] if (i+1) < total_samples else stereo_shorts[i]
                    
                    #mono_sample = (left + right) // 2
                    # 현재 코드의 변조 규칙(left 채널 고정 복사) 유지
                    mono_sample = left
                    mono_shorts.append(mono_sample)
                
                mono_bytes = struct.pack(f"{len(mono_shorts)}h", *mono_shorts)
                
                if len(mono_bytes) == TARGET_SIZE:
                    audio_queue.put(mono_bytes, block=False)
                    
        except queue.Full:
            pass  
        except Exception as e:
            print(f"[-] [Capture] 런타임 에러: {e}")
            break
            
    print("[-] [Capture] 오디오 캡처 스레드가 종료되었습니다.")



def main():
    global running, config
    
    if len(sys.argv) < 2:
        print("[-] 사용법 에러: JSON 설정 파일 경로를 지정해야 합니다.")
        print(f'    예시: python3 {sys.argv[0]} config.json')
        sys.exit(1)
        
    config_path = sys.argv[1]
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"[+] '{config_path}' 설정 파일을 성공적으로 불러왔습니다.")
    except Exception as e:
        print(f"[-] JSON 설정을 읽어오는 중 에러 발생: {e}")
        sys.exit(1)

    client_name = f"{config['bot_name']}"
    mumble = None

    print(f"\n[+] 고정 닉네임 '{client_name}'으로 Mumble 서버 연결을 시도합니다... ({config['mumble_server']})")
    
    try:
        mumble = pymumble.Mumble(
            config['mumble_server'], 
            client_name, 
            port=config['mumble_port'], 
            password=config['mumble_password']
        )
        mumble.set_application_string("Pure ALSA Mumble Broadcaster")
        mumble.start()
        
        connection_timeout = 15.0
        start_time = time.time()
        
        print("[+] 서버 반응 대기 및 채널 가로채기 감시 시작...")
        while not mumble.is_ready():
            if time.time() - start_time > connection_timeout:
                raise TimeoutError("Mumble 서버 응답 시간 초과 (Timeout)")
            
            if not mumble.is_alive():
                raise ConnectionError("Mumble 내부 연결 스레드가 비정상 종료되었습니다. (서버 다운 의심)")
            
            if len(mumble.channels) > 1:
                print(f"[+] 핸드셰이크 완료 전 채널 {len(mumble.channels)}개 선제 확보!")
                break
            time.sleep(0.2)
            
        print(f"[+] Mumble 서버 세션 동기화 완료!")
        
        try:
            bandwidth = config.get("mumble_bandwidth_bps", 64000)
            mumble.set_bandwidth(bandwidth)
            print(f"[+] 봇 송출 대역폭 설정 완료: {bandwidth / 1000} kbit/s")
        except Exception as e:
            print(f"[!] 대역폭 설정 중 예외 발생 (스킵): {e}")

        # ------------------ [채널 목록 출력 레이어] ------------------
        print("\n" + "="*50)
        print("              [ MUMBLE ROOM LIST ]              ")
        print("="*50)
        for ch_id, ch_obj in mumble.channels.items():
            print(f" - Room ID: {ch_id:<3} | Name: {ch_obj['name']}")
        print("="*50 + "\n")

        # ------------------ [강제 채널 이동 기습 작전] ------------------
        target_channel = config['target_channel']
        print(f"[+] '{target_channel}' 방으로 즉시 이동 패킷을 송신합니다...")
        moved_success = False
        
        try:
            target_ch = mumble.channels.find_by_name(target_channel)
            if hasattr(target_ch, "move_in"):
                target_ch.move_in()
            else:
                mumble.users.myself.move_in(target_ch["channel_id"])
                
            print(f"[+] [성공] '{target_channel}' 채널로 순간 이동했습니다.")
            moved_success = True
            
        except Exception as channel_error:
            print(f"[-] 서버에서 지정된 방('{target_channel}')을 찾을 수 없습니다. 에러: {channel_error}")
            moved_success = False

        # 지정한 채널이 없거나 이동에 실패하면 즉시 정리 후 종료
        if not moved_success:
            print("[!] 지정된 채널이 존재하지 않아 안전하게 스크립트를 종료합니다.")
            running = False
            if mumble:
                mumble.stop()
            sys.exit(1)

        # ------------------ [오디오 스트리밍 스레드 가동] ------------------
        capture_t = threading.Thread(target=audio_capture_thread)
        sender_t = threading.Thread(target=mumble_sender_thread, args=(mumble,))
        
        capture_t.daemon = True
        sender_t.daemon = True
        
        capture_t.start()
        sender_t.start()

        # ------------------ [24시간 모니터링 메인 루프] ------------------
        print("[+] 24/7 오디오 송출 및 세션 상주 상태 돌입 (Ctrl+C 종료)")
        while running:
            if mumble and not mumble.is_alive():
                print("[-] Mumble 세션 단절이 감지되었습니다.")
                break
            if not capture_t.is_alive() or not sender_t.is_alive():
                print("[-] 오디오 서브시스템 스레드가 다운되었습니다.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[INFO] 사용자가 인터럽트(Ctrl+C)를 호출했습니다.")
        running = False
    except (ConnectionRefusedError, TimeoutError, Exception) as e:
        # 💥 [핵심 변경] 런타임 예외 발생 시 재시도 플래그를 완전히 끄고 즉시 종료 프로세스로 이동
        print(f"\n[-] 가동 중 크리티컬 예외 발생: {e}")
        running = False
    finally:
        # 예외 유무와 상관없이 무조건 1회만 자원 정리를 깔끔하게 처리하고 끝냅니다.
        print("[+] 자원을 정리하고 스크립트를 완전히 안전하게 종료(Graceful Shutdown)합니다...")
        if mumble:
            try: mumble.stop()
            except: pass
            
        if not running:
            print("[+] 모든 프로세스가 안전하게 정상 종료되었습니다.")
            sys.exit(1)


if __name__ == "__main__":
    main()