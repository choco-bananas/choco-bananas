import struct


def parse(data, msg):
    """
    :param data: temp file with remaining message data to parse (header has been read by response_handler
    :param msg: expecting a child class of Structure for the desired message (msg). The function checks type for this
    since the msg may not be currently handled. In this case, a type error is raised and message printed to terminal.
    :return: NA
    """
    if type(msg).__mro__[1] is not Structure:
        raise TypeError
    print(f"Parsing data for {msg}")
    response = msg.from_file(data)
    if response.count:
        if response.count is not 1:
            print(f'There are {response.count} messages in the reply!')
        else:
            print(f'There is one message in the reply!')
        msg.add_fields(response.count)
    msg.parse(response)


class StructField:
    """
    Descriptor representing a simple structure field (Python Cookbook p. 224)
    """
    def __init__(self, format, offset):
        self.format = format
        self.offset = offset

    def __get__(self, instance, cls):
        if instance is None:
            return self
        else:
            r = struct.unpack_from(self.format,
                                   instance._buffer, self.offset)
            return r[0] if len(r) == 1 else r


class StructureMeta(type):
    """
    Metaclass that automatically creates StructField descriptors
    """

    def __init__(self, clsname, bases, clsdict):
        fields = getattr(self, '_fields_', [])
        byte_order = ''
        offset = 0
        for format, fieldname in fields:
            if format.startswith(('<', '>', '!', '@')):
                byte_order = format[0]
                format = format[1:]
            format = byte_order + format
            setattr(self, fieldname, StructField(format, offset))
            offset += struct.calcsize(format)
        setattr(self, 'struct_size', offset)


class Structure(metaclass=StructureMeta):

    def __init__(self, bytedata):
        self._buffer = bytedata

    @classmethod
    def from_file(cls, f):
        return cls(f.read(cls.struct_size))


class MessageHandler(Structure):
    """
    All messages Rx'd start with this
    """
    _fields_ = [
        ('>H', 'START'),
        ('H', 'size'),
        ('H', 'msg_id'),
        ('B', 'flags'),
        ('I', 'tag'),
        ('B', 'schema')
    ]


class ActionStatus(Structure):
    _fields_ = [
        ('>H', 'action_type'),
        ('H', 'host_ip_addr'),
        ('H', 'action_zero'),
        ('H', 'action_one'),
        ('H', 'action_two'),
        ('H', 'action_three'),
        ('B', 'info'),
        ('B', 'action_type'),
    ]

    def __str__(self):
        return "Reply Action Status"


class AliasStatus(Structure):
    _fields_ = [
        ('>H', 'count'),
        ('H', 'reserved_zero1'),
        ('B', 'system_number1'),
        ('B', 'entity_type1'),
        ('B', 'entity_instance_msb1'),
        ('B', 'entity_instance_lsb1'),
        ('20s', 'alias_text1'),
        ('H', 'unicode marker1'),
    ]

    def parse(self, response):

        entity_types = {
            1: 'Port',
            2: 'Conference',
            3: 'Fixed Group',
            4: 'IFB'
        }
        print(f'System Number: {response.system_number1}')
        print(f'{entity_types.get(response.entity_type1)} {response.entity_instance_lsb1}', end='')
        print(f" has changed name to: {response.alias_text1.decode('utf-16be')}")

    def add_fields(self, count):
        """
        Takes the count and uses it to increase the number of fields to parse
        :param count: int - number of messages in the reply
        :return: NA
        """
        for msg_number in range(count):
            self._fields_.extend([
                ('H', f'reserved_zero{str(msg_number+2)}'),
                ('B', f'system_number{str(msg_number+2)}'),
                ('B', f'entity_type{str(msg_number+2)}'),
                ('B', f'entity_instance_msb{str(msg_number+2)}'),
                ('B', f'entity_instance_lsb{str(msg_number+2)}'),
                ('20s', f'alias_text{str(msg_number+2)}'),
                ('H', f'unicode marker{str(msg_number+2)}'),
            ])

    def __str__(self):
        return "Reply Alias Status (Unicode)"
