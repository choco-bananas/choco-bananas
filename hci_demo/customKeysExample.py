# customKeysExample.py
# V12RDパネル Listenキーのロータリー操作で Port 2→3 クロスポイントの音量を 0.355dB 刻みで上下制御（Mainページ対応）

import socket
import config
import hxrequests
import struct
import time
import ehxHelper
import binascii

BUFFER_SIZE = 1024

# AUDIO_LEVEL.xml 対応のゲインバイナリ値（例：0.355dBステップ）
audio_levels = [
    90, 103, 116, 129, 142, 155, 168, 181, 194, 207, 220, 233, 246, 255
]  # -10dB ～ +3dB相当

current_level_index = 7  # 初期ゲインインデックス（0.355dB刻み中間）

def set_crosspoint_level(sock, level_value):
    # ポート2→3のクロスポイントレベル変更
    source = 2
    destination = 3
    data = hxrequests.xpt_action_tx([(source, destination, level_value)])
    sock.send(data)
    print(f"Set level: {level_value} for XPT 2→3")

def enable_auto_update(sock):
    EHX_message = ehxHelper.pack_ehx_message(318, None, None, None, None, None, None, None, None)
    sock.send(EHX_message)
    print("Sent auto update enable request")
    response = sock.recv(BUFFER_SIZE)
    print("Received:", binascii.hexlify(response))
    header = ehxHelper.parse_header(response)
    if header:
        payload = ehxHelper.parse_payload(header, response, sock)
        if payload and payload[3] == 1:
            print("Auto update enabled")
            return True
    print("Auto update failed or not acknowledged")
    return False

def run_rotary_level_control():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((config.matrixIP, config.matrixPort))

    if not enable_auto_update(sock):
        sock.close()
        return

    print("Listening for Listen key presses to adjust level on Page 0 (Main Page)...")
    global current_level_index
    while True:
        payload_received = sock.recv(BUFFER_SIZE)
        header = ehxHelper.parse_header(payload_received)
        if header:
            payload = struct.unpack_from("!hhbbbb", payload_received, 12)
            panel, region, page, key, state = payload[0], payload[1], payload[2], payload[3], payload[4]
            print(f"Key Event: Panel={panel} Region={region} Page={page} Key={key} State={state}")
            if region == 1 and page == 0 and key == 1:
                if state == 1:
                    current_level_index = min(current_level_index + 1, len(audio_levels) - 1)
                    set_crosspoint_level(sock, audio_levels[current_level_index])
                elif state == 2:
                    current_level_index = max(current_level_index - 1, 0)
                    set_crosspoint_level(sock, audio_levels[current_level_index])

if __name__ == '__main__':
    print("--- Running Rotary Level Control (Main Page 0) ---")
    run_rotary_level_control()
