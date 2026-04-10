import struct
import binascii
import config

# HCI Message Constants
START = 23055
END = 11917
MAGIC_NUMBER = 2881146590
SCHEMA = 1
H2C_FLAG = 8
REQ_REM_ALIAS_ASCII = 129


def alias_tx(targets, add=True):
    """
    :param targets: list of tuples (system, page, key, alias_string)
    :param add: bool - True to add alias, False to remove
    :return: bytes packed for socket transmission
    """
    message_id = REQ_REM_ALIAS_ASCII if add else 132
    header_struct = struct.Struct(">3HBI2B2H")  # Expecting 9 items
    alias_entries = []
    alias_payload = b""

    for system, page, key, alias in targets:
        alias_bytes = alias.encode('ascii')
        alias_len = len(alias_bytes)
        alias_entries.append((system, page, key, alias_len, alias_bytes))

    count = len(alias_entries)
    reserved1 = 0
    reserved2 = 0
    header = (START, 0, message_id, H2C_FLAG, MAGIC_NUMBER, SCHEMA, count, reserved1, reserved2)

    # build payload dynamically
    for system, page, key, alias_len, alias_bytes in alias_entries:
        entry = struct.pack(">3BH", system, page, key, alias_len) + alias_bytes
        alias_payload += entry

    total_size = header_struct.size + len(alias_payload) + 2  # +2 for END
    header = (START, total_size, message_id, H2C_FLAG, MAGIC_NUMBER, SCHEMA, count, reserved1, reserved2)
    packed_header = header_struct.pack(*header)
    packed_footer = struct.pack(">H", END)

    if config.DEBUG:
        print("---- DEBUG LOG ----")
        print("Packed Header + Payload + Footer:")
        print(binascii.hexlify(packed_header + alias_payload + packed_footer))

    return packed_header + alias_payload + packed_footer


# 実行例：V12RDのMainページ（Page 0）左上キーにラベルを設定
if __name__ == '__main__':
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((config.matrixIP, config.matrixPort))

    aliases = [
        (1, 0, 0, "2"),      # Key 0 on Page 0: Talk to Port 2
        (1, 0, 1, "3")       # Key 1 on Page 0: Listen to Port 3
    ]

    s.send(alias_tx(aliases, add=True))
    print("Aliases sent: 2, 3 (Page 0)")
    s.close()
