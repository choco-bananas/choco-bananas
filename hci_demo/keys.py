"""
General key assignment function (Tx)
"""
import binascii
import collections
import struct

# HCI Messages
START = 23055
END = 11917
MAGIC_NUMBER = 2881146590
SCHEMA = 1
H2C_FLAG = 8
REQ_REM_KEY_ACTION = 235

KeyActionData = collections.namedtuple('KeyActionData',
                                       ['region',
                                        'page',
                                        'key',
                                        'entity_type',
                                        'entity_sys',
                                        'entity_number',
                                        'key_activation'])


def assign_keys_tx(target, actions):
    """
    :param target: int - port number (1-based) of target panel for key assignment
    :param actions: list of KeyActionData objects (see above namedtuple)
    :return: struct.pack'd data to be sent out on the socket
    """
    target = target - 1     # convert 1-based to 0-based
    struct_string = '>3HBI2B2H'
    assignment_type = 1     # All other types reserved for future use (manual p. 151)
    latch_mode = 0          # Currently always 0 (manual p. 153)
    count = len(actions)
    actions_data = list()
    for region, page, key, entity_type, entity_sys, entity_number, key_activation in actions:
        actions_data.extend([region, page, key])
        actions_data.extend([0, 0])      # Reserved byte + always zero entity_type byte
        actions_data.extend([entity_type, entity_sys])
        actions_data.append(0)       # Reserved byte
        actions_data.extend([entity_number, key_activation, latch_mode])
        struct_string = struct_string + '8BH2B'
    struct_string = struct_string + 'H'     # for END
    key_assign_struct = struct.Struct(struct_string)
    size = key_assign_struct.size
    header = START, size, REQ_REM_KEY_ACTION, H2C_FLAG, MAGIC_NUMBER, SCHEMA, assignment_type, count, target
    variable_data = tuple(actions_data)
    footer = (END,)
    print(header + variable_data + footer)
    data = key_assign_struct.pack(*(header + variable_data + footer))
    print(binascii.hexlify(data))
    return data
