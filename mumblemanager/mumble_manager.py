# --- Python 3.12+ 호환성을 위한 ssl.wrap_socket 몽키 패치 (개선판) ---
import ssl
import socket

if not hasattr(ssl, "wrap_socket"):
    def legacy_wrap_socket(sock, keyfile=None, certfile=None, server_side=False,
                           cert_reqs=ssl.CERT_NONE, ssl_version=None, ca_certs=None,
                           do_handshake_on_connect=True, suppress_ragged_eofs=True,
                           ciphers=None):
        
        # 3.12+ 버전에서는 TLS_CLIENT 또는 TLS_SERVER를 명시해야 합니다.
        purpose = ssl.Purpose.SERVER_AUTH if not server_side else ssl.Purpose.CLIENT_AUTH
        context = ssl.create_default_context(purpose, cafile=ca_certs)
        
        # Mumble 클라이언트 호환성을 위해 기본 검증 완화
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        if certfile:
            context.load_cert_chain(certfile, keyfile)
        if ciphers:
            context.set_ciphers(ciphers)
            
        return context.wrap_socket(sock, server_side=server_side,
                                   do_handshake_on_connect=do_handshake_on_connect,
                                   suppress_ragged_eofs=suppress_ragged_eofs)
                                   
    # ssl 모듈 자체에 주입하여 모든 스레드가 공유하도록 설정
    ssl.wrap_socket = legacy_wrap_socket
# --- 몽키 패치 끝 ---


import json
import time
import sys
from pymumble_py3 import Mumble
from pymumble_py3 import constants

from datetime import datetime
import builtins

# 유저들의 현재 채널 ID를 실시간으로 추적할 캐시 딕셔너리 (Key: session, Value: channel_id)
user_room_cache = {}

_original_print = builtins.print

def print(*args, **kwargs):
    ts = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    _original_print(ts, *args, **kwargs)
    

def load_config(filename="config.json"):
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)



def apply_acl_list_properties(user):
    # --- user 객체 내부 들여다보기 코드 시작 ---
    print("\n" + "="*40)
    print(f"[{user['name']}] 유저 객체 분석")
    print("="*40)
    
    # 1. 객체가 가진 모든 속성과 메서드 이름 목록 (dir)
    print("\n[1. 모든 속성/메서드 이름 목록]")
    print(dir(user))
    
    # 2. 객체가 현재 가지고 있는 '실제 데이터 값' 목록 (vars 또는 __dict__)
    print("\n[2. 현재 저장된 데이터 값 (Key-Value)]")
    try:
        # vars()는 객체의 __dict__를 보기 좋게 반환합니다.
        for key, value in vars(user).items():
            print(f"  {key}: {value}")
    except TypeError:
        # 만약 slots 등을 사용해 __dict__가 없다면 내장 딕셔너리 확인
        if hasattr(user, "data"):
            print("  (data 딕셔너리 발견):", user.data)
    print("="*40 + "\n")
    # --- 분석 코드 끝 ---


def apply_acl(user):
    cfg = load_config()
    
    # 딕셔너리 구조에 맞게 상태 추출 (Key가 없으면 기본값 False)
    # Mumble 특성상 Unmute 상태일 땐 딕셔너리에 'mute' Key 자체가 없을 수 있습니다.
    is_muted = bool(user.get("mute", False))
    is_suppressed = bool(user.get("suppress", False))
    
    # 1. ServerMute 리스트에 포함된 관리 대상(허가된 사용자)인 경우 -> Unmute / Unsuppress
    if user["name"] in cfg["ServerMute"]:
        need_unmute = is_muted
        need_unsuppress = is_suppressed

        if need_unmute or need_unsuppress:
            if need_unmute:
                user.unmute()
            if need_unsuppress:
                user.unsuppress()
            print(f'[{user["name"]}] 상태 변경 -> unmute, unsuppress !!')
            
    # 2. ServerMute 리스트에 없는 일반 사용자인 경우 -> Mute / Suppress 처리
    else:
        print(f'User name {user["name"]} is not granted')
        print(f'현재 상태 - mute: {is_muted}, suppress: {is_suppressed}')
        
        # 현재 해제(False) 상태인 항목만 찾아서 차단(True) 명령을 보냅니다.
        need_mute = not is_muted
        need_suppress = not is_suppressed
        
        if need_mute or need_suppress:
            if need_mute:
                user.mute()
            if need_suppress:
                user.suppress()
            print(f'[{user["name"]}] 상태 변경 -> mute, suppress !! (Unmanaged User)')


def show_channel(mb):
    print("=== Channels ===")
    for channel_id, channel in mb.channels.items():
        print(f"[{channel_id}] {channel['name']}")


def show_user(mb):
    print("=== Users ===")
    for session_id, user in sorted(mb.users.items()):
        channel = mb.channels[user["channel_id"]]
        
        # pymumble의 유저 식별자 키는 'session'입니다.
        user_room_cache[user["session"]] = user["channel_id"]

        print(f"{user['name']:20s} Room={channel['name']:15s} ")
        apply_acl(user)


def on_user_created(user):
    mb = user.mumble_object
    channel_id = user["channel_id"]
    channel = mb.channels[channel_id]["name"]
    print(f"[JOIN] {user['name']} -> {channel}")
    
    # 새로운 유저가 들어오면 캐시에 추가 및 ACL 적용
    user_room_cache[user["session"]] = channel_id
    apply_acl(user)



def on_user_removed(user, message):
    print(f"[LEAVE] {user['name']}")
    # 유저가 나가면 캐시에서 삭제
    if user["session"] in user_room_cache:
        del user_room_cache[user["session"]]


def on_user_updated(user, actions):
    mb = user.mumble_object

    # 채널 이동 감지 블록
    if "channel_id" in actions:
        print(f"[UPDATE] {user['name']}")  # MOVE가 있을 때만 UPDATE 로그 출력
        session = user["session"]
        new_ch_id = user["channel_id"]
        
        old_ch_id = user_room_cache.get(session, actions["channel_id"])
        
        old_ch = mb.channels.get(old_ch_id, {}).get("name", f"Unknown({old_ch_id})")
        new_ch = mb.channels.get(new_ch_id, {}).get("name", f"Unknown({new_ch_id})")

        print(f"    MOVE : {old_ch} -> {new_ch}")
        
        # 캐시 업데이트
        user_room_cache[session] = new_ch_id

        # ★ 오직 채널 '이동'이 감지되었을 때만 딱 한 번 ACL 함수를 실행합니다.
        apply_acl(user)
        return  # 채널 이동 처리를 했으므로 함수를 종료하여 아래의 일반 상태 로그와 겹치지 않게 합니다.

    # 채널 이동 외에 단순 상태 변경 로그 (원하지 않으면 이 아래 블록들은 주석 처리하셔도 됩니다)
    # 다만 apply_acl로 인해 이 변경이 들어와도 위에서 return되거나 상태 체크로 무한 루프가 안 납니다.
    if "self_mute" in actions:
        print(f"[UPDATE] {user['name']} -> SelfMute = {user.get('self_mute')}")

    if "mute" in actions:
        print(f"[UPDATE] {user['name']} -> ServerMute = {user.get('mute')}")

    if "suppress" in actions:
        print(f"[UPDATE] {user['name']} -> Suppress = {user.get('suppress')}")


def main():
    cfg = load_config()

    mumble = Mumble(
        cfg["server"],
        cfg["su"],
        port=cfg.get("port", 64738),
        password=cfg["supassword"]
    )

    print(f'Start mumble with username : {cfg["su"]}, password: {cfg["supassword"]}')
    mumble.start()
    
    for i in range(100):
        print(f"\rWaiting... {i+1}/100", end="", flush=True)

        if mumble.connected == constants.PYMUMBLE_CONN_STATE_CONNECTED:
            print("\nConnected!")
            break
        else:
            print(f'mumble con status = {mumble.connected}')

        time.sleep(0.2)
    else:
        print("\nERROR: Mumble connection timeout.")
        sys.exit(1)
        
    print("mumble server is ready")


    show_channel(mumble)
    show_user(mumble)
    print(f'Granted user = {cfg["ServerMute"]}')
    mumble.callbacks.set_callback(constants.PYMUMBLE_CLBK_USERCREATED, on_user_created)
    mumble.callbacks.set_callback(constants.PYMUMBLE_CLBK_USERREMOVED, on_user_removed)
    mumble.callbacks.set_callback(constants.PYMUMBLE_CLBK_USERUPDATED, on_user_updated)


    try:
        while True:
            # ★ 핵심: 주기적으로 mumble 서버와의 연결 상태를 감시합니다.
            if not mumble.is_alive():
                print("\n[ERROR] Mumble server connection lost! (Thread is dead)")
                print(f'mumble con status = {mumble.connected}')
                break
                
            if mumble.connected != constants.PYMUMBLE_CONN_STATE_CONNECTED:
                print("\n[ERROR] Mumble disconnected from server.")
                break

            time.sleep(0.1)  # CPU 점유율을 위해 0.1초 정도로 변경 권장
            
    except KeyboardInterrupt:
        print("\n[INFO] Stopping by user interrupt...")
    except Exception as e:
        print(f"\n[CRITICAL] Unexpected error: {e}")
    finally:
        # 무한 루프를 빠져나오거나 예외가 발생하면 반드시 멈추고 종료 처리
        print("[INFO] Cleaning up mumble connection...")
        mumble.stop()
        print("[INFO] Process exited safely.")
        sys.exit(1)


if __name__ == "__main__":
    main()