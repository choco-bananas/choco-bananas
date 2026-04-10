#!/usr/bin/python
import struct
import binascii
import HCImessageID as msg_id
import config as config


EHX_FLAGS = 8
EHX_MAGIC_NUMBER = 2881146590
EHX_SCHEMA_NUMBER = 1
EHX_PORT_NUMBER_START = 0
EHX_PORT_NUMBER_END = 495
EHX_ENABLED_DISABLED = 1

def pack_ehx_message(msg, str_display, panel, region, page, key, color, brighthnes, icon):
    """
    Pack the HCI message to send to EHX
    :param msg:
    :param str_display:
    :param panel:
    :param region:
    :param page:
    :param key:
    :param color:
    :param brighthnes:
    :param icon:
    :return:
    """
    global EHX_message
    s = struct.Struct('!h h')
    if panel == 0:
        panel = config.panelPort
    values = (0, 0)
    # print("HCI message {0}".format(msg))
    if msg == msg_id.ECS_HCI_GET_PROXY_INDICATION_STATE_REQUEST:  # 310
        msg = [msg_id.ECS_HCI_GET_PROXY_INDICATION_STATE_REQUEST, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, 65535]
        s = struct.Struct('!H h h b I b H h')
        values = (0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], 0x2E8D)

    elif msg == msg_id.ECS_HCI_SET_PROXY_INDICATION_STATE_REQUEST:  # 312
        msg = [msg_id.ECS_HCI_SET_PROXY_INDICATION_STATE_REQUEST, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, 1,
               panel, region, page, key, color, brighthnes, 0]
        s = struct.Struct('!H H h b I b h h b b b b b b h')
        values = (
            0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], msg[6],
            msg[7], msg[8], msg[9], msg[10], msg[11], 0x2E8D)

    elif msg == msg_id.ECS_HCI_GET_PROXY_DISPLAY_STATE_REQUEST:  # 314
        s = struct.Struct('!H h h b I b H h')
        values = (0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], 0x2E8D)

    elif msg == msg_id.ECS_HCI_SET_PROXY_DISPLAY_STATE_REQUEST:  # 316
        msg = [msg_id.ECS_HCI_SET_PROXY_DISPLAY_STATE_REQUEST, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, 1, panel,
               region,
               page, key, str_display.encode('utf-16-be'), b"2", color, icon]
        s = struct.Struct('!H h h b I b H H b b b 20s 20s B h h')
        values = (
            0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], msg[6],
            msg[7], msg[8], msg[9], msg[10], msg[11], msg[12], 0x2E8D)

    elif msg == msg_id.ECS_HCI_KEY_STATUS_AUTO_UPDATES_REQUEST:  # 318
        msg = [msg_id.ECS_HCI_KEY_STATUS_AUTO_UPDATES_REQUEST, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER,
               EHX_PORT_NUMBER_START, EHX_PORT_NUMBER_END, EHX_ENABLED_DISABLED]
        s = struct.Struct('!H h h b I b H H b h')

        values = (
            0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], msg[6], 0x2E8D)
        EHX_message = s.pack(*values)
    elif msg == 177:
        msg = [177, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, 3, 0]
        s = struct.Struct('!H h h b I b b b h')
        values = (0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], 0x2E8D)

    EHX_message = s.pack(*values)
    if config.DEBUG:
        print("-------------------------------------")
        print("MSG TO SEND:", EHX_message)
        print("-------------------------------------")

    return EHX_message


def parse_header(packet_data):
    """
    Parse the header of the MSG received
    :param packet_data: data packet
    :return: returns an array containing rx_length {0}, msg_id {1}, msg_flag {2}, magic_no {3}
    """
    if len(packet_data) > 10:
        # print(binascii.hexlify(data))
        params = struct.unpack("!h b I", packet_data[4:11])
        rx_start = struct.unpack("!h", packet_data[0:2])
        if params[2] == 0xABBACEDE:
            if rx_start[0] == 0x5A0F:
                header = struct.unpack("!h h b I b", packet_data[2:12])
                if config.DEBUG:
                    print("-------------------------------------")
                    print(binascii.hexlify(packet_data))
                    print("RX_length                :", header[0])
                    print("MSG ID                   :", header[1])
                    print("MSG FLAG                 :", header[2])
                    print("Magic Number             :", header[3])
                    print("Schema Number            :", header[4])
                    print("-------------------------------------")
                return header
            else:
                return False
        else:
            return False
    else:
        return False

def parse_payload(header, payload_data, sock):
    """
    Parse the Payload of the MSG
    :param header:
    :param payload_data:
    :param sock:
    :return:
    """
    if header[1] == msg_id.ECS_HCI_KEY_STATUS_AUTO_UPDATES_REPLY:
        #print("ECS_HCI_KEY_STATUS_AUTO_UPDATES_REPLY msg received")
        return handle_key_status_auto_updates_reply(payload_data[11:])
    elif header[1] == msg_id.ECS_HCI_GET_PROXY_INDICATION_STATE_REPLY:
        #print("ECS_HCI_GET_PROXY_INDICATION_STATE_REPLY msg received")
        return handle_get_proxy_indication_state_reply(payload_data[11:], header)
    elif header[1] == msg_id.ECS_HCI_SET_PROXY_INDICATION_STATE_REPLY:
        #print("ECS_HCI_SET_PROXY_INDICATION_STATE_REPLY msg received")
        return handle_set_proxy_indication_state_reply(payload_data[11:], header)
    elif header[1] == msg_id.EHX_MSG_ID_KEY_PRESSED_STATUS_REPLY:
        #print("EHX_MSG_ID_KEY_PRESSED_STATUS_REPLY msg received")
        handle_key_status_reply(payload_data[11:],sock)
    elif header[1] == msg_id.ECS_HCI_GET_PROXY_DISPLAY_STATE_REPLY:
        print("ECS_HCI_GET_PROXY_DISPLAY_STATE_REPLY msg received")
        print(binascii.hexlify(payload_data))
        handle_get_display_status_reply(payload_data[12:])
    else:
        print("Message is unknown")
        return False


def handle_get_display_status_reply(payload):
    """

    """
    print(binascii.hexlify(payload))
    no_entries = struct.unpack("!h", payload[0:2])
    entries = payload[2:]
    print(binascii.hexlify(entries))
    segment = 1
    while no_entries[0] != segment:
        data = struct.unpack("!h b b b 20s 20s b h 40s", entries[(segment-1)*88:segment*88])
        segment = segment + 1
        if config.DEBUG is not 1:
            #payload_entry = struct.unpack("!h b b b b b b", payload[payload_offset:payload_offset + 8])
            print("-------------------------------------")
            print("Panel                   :", data[0])
            print("Region                  :", data[1])
            print("Page                    :", data[2])
            print("Key                     :", data[3])
            print("Text                    :", data[4])
            print("Alt Text                :", data[5])
            print("Gain level              :", data[6])
            print("Icons                   :", data[7])
            print("-------------------------------------")
    return data

def handle_key_status_auto_updates_reply(payload):
    """
    Parse the payload for Key Status Auto Update
    Informs us if the auto update is enabled or not.
    :param payload:
    :return: Schema {0}, PortStart {1}, PortEnd {2}, Enable {3}
    """
    payload_data1 = struct.unpack("!b h h b", payload[0:6])
    if config.DEBUG:
        print("-------------------------------------")
        print("Schema Number            :", payload_data1[0])
        print("PortStart                :", payload_data1[1])
        print("PortEnd                  :", payload_data1[2])
        print("Enable                   :", payload_data1[3])
        print("-------------------------------------")
    return payload_data1

def handle_set_proxy_indication_state_reply(payload, header):
    """
    Parse the payload for Proxy Indication State reply
    :param payload:
    :param header:
    :return:
    """
    payload_header = struct.unpack("!b h", payload[0:3])
    if payload_header[0] == 1:
        # Only support schema 1 for this message (currently)
        entries_left = payload_header[1]
        payload_offset = 3
        if payload_header[1] == 0:
            print("No data in msg_id: {0}".format(header[1]))
        while entries_left > 0:
            entries_left -= 1
            if config.DEBUG:
                payload_entry = struct.unpack("!h b b b b b b", payload[payload_offset:payload_offset + 8])
                print("-------------------------------------")
                print("Panel                   :", payload_entry[0])
                print("Region                  :", payload_entry[1])
                print("Page                    :", payload_entry[2])
                print("Key                     :", payload_entry[3])
                print("Colour                  :", payload_entry[4])
                print("Rate                    :", payload_entry[5])
                print("MIC                     :", payload_entry[6])
                print("-------------------------------------")


def handle_key_status_reply(payload,sock):
    """
    Handel a status change of a key
    :param payload:
    :param sock:
    :return:
    """
    global volume

    payload_header = struct.unpack("!b b", payload[0:2])
    if payload_header[0] == 1:
        # Only support schema 1 for this message (currently)
        entries_left = payload_header[1]
        payload_offset = 2

        while entries_left > 0:
            payload_entry = struct.unpack("!h b b b b", payload[payload_offset:payload_offset + 6])

            panel = payload_entry[0]
            region = payload_entry[1]
            page = payload_entry[2]
            key = payload_entry[3]
            state = payload_entry[4]
            entries_left -= 1
            if config.DEBUG:
                print("-------------------------------------")
                print("Panel                  :", panel)
                print("Region                 :", region)
                print("Page                   :", page)
                print("Key                    :", key)
                print("State                  :", state)
                print("-------------------------------------")

            if state != 0:
                print("Key %s on pannel %s on page %s was pressed" % (key, panel, page))
                if key % 4 == 0:
                    #change text and bar and icon
                    EHX_message = setTextBarIcon(panel,region,page,key,("k:%s,r%s" % (key,region)),b"2",15,0x02)
                    sock.send(EHX_message)
                    #print(binascii.hexlify(EHX_message))

                    payload_received = bytes(sock.recv(config.BUFFER_SIZE))
                    # print(binascii.hexlify(payload_received))
                    header = parse_header(payload_received)


                    #set color and refresh rate
                    EHX_message = setColor(panel,region,page,key,0x5,0x2,0)
                    print("Sending: %s" % (binascii.hexlify(EHX_message)))
                    sock.send(EHX_message)
                elif (key-1) % 4 == 0:
                    #change text and bar and icon
                    EHX_message = setTextBarIcon(panel,region,page,key-1,("k:%s,r%s" % (key,region)),b"2",15,0x02)
                    sock.send(EHX_message)

                    # set color and refresh rate
                    EHX_message = setColor(panel, region, page, key, 0x3, 0x2, 0)
                    print("Sending: %s" % (binascii.hexlify(EHX_message)))
                    sock.send(EHX_message)
                elif (key-2) % 4 == 0:
                    # change text and bar and icon
                    EHX_message = setTextBarIcon(panel, region, page, key-2, ("k:%s,r%s" % (key, region)), b"2", 10, 0x02)

                    # request display data:
                    MESSAGE =getDisplayState(panel)
                    print("Sending get display: %s" % (binascii.hexlify(MESSAGE)))
                    sock.send(MESSAGE)
                    stateReceived = False
                    while stateReceived is not True:
                        payload_received = bytes(sock.recv(config.BUFFER_SIZE))
                        # print(binascii.hexlify(payload_received))
                        header = parse_header(payload_received)
                        if header:
                            payload = parse_payload(header, payload_received, sock)
                            if payload is not False:
                                print("test")

                    print("Sending: %s" % (binascii.hexlify(EHX_message)))

                    sock.send(EHX_message)

                elif (key-3) % 4 == 0:
                    # change text and bar and icon
                    EHX_message = setTextBarIcon(panel, region, page, key-3, ("k:%s,r%s" % (key, region)), b"2", 5, 0x02)
                    print("Sending: %s" % (binascii.hexlify(EHX_message)))
                    sock.send(EHX_message)





            else:
                print("Key %s on pannel %s on page %s was released" % (key, panel, page))


def setTextBarIcon(port,region,page,key,text,altText,gain,icon):
        msg = [msg_id.ECS_HCI_SET_PROXY_DISPLAY_STATE_REQUEST, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, 1, port,
               region,
               page, key, text.encode('utf-16-be'), b"2", gain, icon]
        s = struct.Struct('!H h h b I b H H b b b 20s 20s B h h')
        values = (
            0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], msg[6],
            msg[7], msg[8], msg[9], msg[10], msg[11], msg[12], 0x2E8D)
        EHX_message = s.pack(*values)
        if config.DEBUG:
            print("-------------------------------------")
            print("MSG TO SEND:", EHX_message)
            print("-------------------------------------")

        return EHX_message

def getDisplayState(port):
    msg = [msg_id.ECS_HCI_GET_PROXY_DISPLAY_STATE_REQUEST,EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, port]
    s = struct.Struct('!H h h b I b H h')
    values = (0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], 0x2E8D)
    EHX_message = s.pack(*values)
    if config.DEBUG:
        print("-------------------------------------")
        print("MSG TO SEND:", EHX_message)
        print("-------------------------------------")

    return EHX_message

def setColor(port, region, page, key, color,rate,mic):
    msg = [msg_id.ECS_HCI_SET_PROXY_INDICATION_STATE_REQUEST, EHX_FLAGS, EHX_MAGIC_NUMBER, EHX_SCHEMA_NUMBER, 1,
           port, region, page, key, color, rate, mic]
    s = struct.Struct('!H H h b I b h h b b b b b b h')
    values = (
        0x5A0F, s.size, msg[0], msg[1], msg[2], msg[3], msg[4], msg[5], msg[6],
        msg[7], msg[8], msg[9], msg[10], msg[11], 0x2E8D)
    EHX_message = s.pack(*values)
    if config.DEBUG:
        print("-------------------------------------")
        print("MSG TO SEND:", EHX_message)
        print("-------------------------------------")

    return EHX_message