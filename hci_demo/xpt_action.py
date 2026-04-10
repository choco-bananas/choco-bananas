import struct
import binascii

# HCI Messages
START = 23055
END = 11917
MAGIC_NUMBER = 2881146590
SCHEMA = 1
H2C_FLAG = 8
matrixIP = '10.50.14.4'  # Joe Frame Z
matrixPort = 52002
XPT_ACTION = 17


def get_words(source, destination, direction=True, enable=True):
    """
    :param source: int source port etc
    :param destination: int destination port
    :param direction: bool true for add; false for delete
    :param enable: bool true for enable; false for inhibit
    :return: list of words for xpt action (etc)
    """

    bit_mask_zero = 9216     # see manual p.40 for fixed bit values
    bit_mask_three = 1018
    xpt_priority = 3    # Must be changed for multi-frame systems
    direction_bit = int(direction)
    # print(f"direction bit: {direction_bit}")
    destination_msbs = destination >> 8
    # print(f"destination msbs: {destination_msbs}")
    source_msbs = source >> 8
    # print(f"source msbs: {source_msbs}")
    destination_lsbs = destination & 255
    # print(f"destination lsbs: {destination_lsbs}")
    source_lsbs = source & 255
    # print(f"source lsbs: {source_lsbs}")
    # print(f"enable: {enable}")
    enable_bit = int(not enable)
    # print(f"enable_bit: {enable_bit}")
    zero = bit_mask_zero + direction_bit + (destination_msbs << 1) + (source_msbs << 8)
    # print(f"word 0: {zero}")
    one = (source_lsbs << 8) + destination_lsbs
    # print(f"word 1: {one}")
    two = 0
    # print(f"word 2: {two}")
    three = bit_mask_three + (enable_bit << 11) + (xpt_priority << 13)
    # print(f"word 3: {three}")
    return [zero, one, two, three]


def xpt_action_tx(xpts, direction=True, enable=True):
    """
    :param xpts: list of tuples of ints of source, destination ports
    :param direction: bool - True = route is made; False = route is inhibited
    :param enable: bool - True = Host to CSU; False = CSU to Host
    :return: struct.pack'd data to be sent out on the socket
    """

    struct_string = '>3HBIBH'
    count = len(xpts)
    action_type = 1  # Xpt action type
    word_list = list()
    for source, destination in xpts:
        word_list.append(action_type)
        word_list.extend(get_words(source, destination, direction, enable))
        struct_string = struct_string + '5H'
    struct_string = struct_string + 'H'     # for END
    xpt_action_struct = struct.Struct(struct_string)
    size = xpt_action_struct.size
    header = START, size, XPT_ACTION, H2C_FLAG, MAGIC_NUMBER, SCHEMA, count
    variable_data = tuple(word_list)
    footer = (END,)
    print(header + variable_data + footer)
    data = xpt_action_struct.pack(*(header+variable_data+footer))
    print(binascii.hexlify(data))
    return data
