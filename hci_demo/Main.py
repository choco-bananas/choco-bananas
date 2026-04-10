import socket
import struct
import time
import datetime
import binascii
import customKeysExample
import hxrequests
import hxreply
import config

START = 23055
END = 11917
MAGIC_NUMBER = 2881146590
HCI_VERSION = 1
H2C_FLAG = 8

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def connect_to_matrix(ip, port):
    global s
    try:
        s.connect((ip, port))
        local_ip, local_port = s.getsockname()
        print(f"✅ Connected to Matrix at {ip}:{port}")
        print(f"📡 Local socket info: {local_ip}:{local_port}")
    except OSError:
        print("❌ No Tx connection to Matrix...")

def test_key_assign():
    from keys import KeyActionData
    PORT = 1
    TALK = 1
    LISTEN = 2

    key_assignments = [
        KeyActionData(region=1, page=0, key=0, entity_type=PORT, entity_sys=6, entity_number=2, key_activation=TALK),
        KeyActionData(region=1, page=0, key=1, entity_type=PORT, entity_sys=6, entity_number=2, key_activation=LISTEN),
    ]

    data = hxrequests.assign_keys_tx(config.panelPort, key_assignments)
    s.send(data)
    response_handler(238)
    print("🎯 Assigned 2→3 Talk/Listen to V12RD Panel (Page 0)")

def response_handler(msg_id):
    msg_dict = {
        1: 'Broadcast System Message',
        8: 'Reply CCF File',
        14: 'Reply Crosspoint Status',
        16: hxreply.ActionStatus(hxreply.Structure),
        20: 'Reply Conference Status',
        40: 'Reply Crosspoint Level Status',
        98: 'Reply Frame Status',
        131: 'Reply Alias Status (ASCII)',
        133: 'Reply Delete Alias',
        236: 'Reply Remote Key Actions',
        238: 'Reply Remote Key Actions Status',
        245: hxreply.AliasStatus(hxreply.Structure),
        260: 'Reply RF Health Status',
        330: 'AoIP Devices Response Status',
    }
    data = s.recv(900)
    with open('temp.bin', 'wb') as f:
        f.write(data)
    with open('temp.bin', 'rb') as f:
        response = hxreply.MessageHandler.from_file(f)
        print(f"START: {response.START}")
        print(f"Size of message: {response.size} bytes")
        print(f"Message ID: {response.msg_id} ({msg_dict.get(response.msg_id, 'Unknown message')})")
        print(f"Flags: {response.flags}")
        print(f"Protocol Tag: {response.tag}")
        print(f"Protocol Schema: {response.schema}")
        if response.msg_id != msg_id:
            response_handler(msg_id)
        else:
            try:
                hxreply.parse(f, msg_dict.get(response.msg_id))
            except TypeError:
                print("Found response message!")

def main():
    connect_to_matrix(config.matrixIP, config.matrixPort)
    if s.fileno() != -1:
        test_key_assign()
    else:
        print("⚠️ 接続に失敗したため、キーアサイン処理をスキップしました。")

if __name__ == '__main__':
    main()
