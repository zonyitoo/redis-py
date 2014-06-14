
from .server import current_server as server
from .storage import key_space
from redis.common.objects import RedisStringObject
from redis.common.utils import abort, close_connection
from redis.common.utils import nargs_greater_equal
import time


@server.command('quit', nargs=0)
def quit_handler(argv):
    '''
    Client request to close connection.


    '''
    close_connection()


@server.command('bitcount', nargs=nargs_greater_equal(1))
def bitcount_handler(argv):
    '''
    Count the number of set bits (population counting) in a string.

    By default all the bytes contained in the string are examined. It is possible to specify the counting
    operation only in an interval passing the additional arguments start and end.

    Like for the GETRANGE command start and end can contain negative values in order to index bytes starting
    from the end of the string, where -1 is the last byte, -2 is the penultimate, and so forth.

    Non-existent keys are treated as empty strings, so the command will return zero.

    .. code::
        BITCOUNT key [start end]

    :return: The number of bits set to 1.
    :rtype: int

    '''

    key, start, end = argv[1], None, None
    if len(argv) == 3 or len(argv) > 4:
        abort(message='syntax error')
    try:
        if len(argv) == 4:
            start, end = int(argv[2]), int(argv[3])
    except ValueError:
        abort(message='value is not an integer or out of range')

    if key not in key_space:
        return 0

    obj = key_space[key]
    if not isinstance(obj, RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    if end == -1:
        end = None
    elif end is not None:
        end += 1

    ba = bitarray.bitarray()
    ba.frombytes(obj.value[start:end])
    return ba.count()


@server.command('bitop', nargs=nargs_greater_equal(3))
def bitop_handler(argv):
    '''
    Perform a bitwise operation between multiple keys (containing string values) and store the result in
    the destination key.

    The BITOP command supports four bitwise operations: AND, OR, XOR and NOT, thus the valid forms to call
    the command are:

    * BITOP AND destkey srckey1 srckey2 srckey3 ... srckeyN
    * BITOP OR destkey srckey1 srckey2 srckey3 ... srckeyN
    * BITOP XOR destkey srckey1 srckey2 srckey3 ... srckeyN
    * BITOP NOT destkey srckey

    As you can see NOT is special as it only takes an input key, because it performs inversion of bits so it
    only makes sense as an unary operator.

    The result of the operation is always stored at destkey.

    .. code::
        BITOP operation destkey key [key ...]

    :return: The size of the string stored in the destination key, that is equal to the size of the longest
             input string.
    :rtype: int

    '''

    operation, destkey, keys = argv[1].upper(), argv[2], argv[3:]
    if operation not in (b'AND', b'OR', b'XOR', b'NOT'):
        abort(message='Don\'t know what to do for "bitop"')

    if operation == b'NOT':
        if len(keys) > 1:
            abort(message='BITOP NOT must be called with a single source key.')

        if keys[0] not in key_space:
            return 0

        if not isinstance(key_space[keys[0]], RedisStringObject):
            abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

        ba = bitarray.bitarray()
        ba.frombytes(key_space[keys[0]].value)
        ba = ~ba
        key_space[destkey] = RedisStringObject(ba.tobytes())
        return len(key_space[destkey].value)

    if operation == b'AND':
        oper_func = lambda a, b: a & b
    elif operation == b'OR':
        oper_func = lambda a, b: a | b
    elif operation == b'XOR':
        oper_func = lambda a, b: a ^ b

    dest_ba = bitarray.bitarray()
    if keys[0] in key_space:
        if not isinstance(key_space[keys[0]], RedisStringObject):
            abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
        dest_ba.frombytes(key_space[keys[0]].value)

    for key in keys[1:]:
        if key not in key_space:
            src_ba = bitarray.bitarray('0' * len(dest_ba))
        else:
            if not isinstance(key_space[key], RedisStringObject):
                abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
            src_ba = bitarray.bitarray()
            src_ba.frombytes(key_space[key].value)

            if len(src_ba) > len(dest_ba):
                dest_ba.extend([0] * (len(src_ba) - len(dest_ba)))
            elif len(dest_ba) > len(src_ba):
                src_ba.extend([0] * (len(dest_ba) - len(src_ba)))

        dest_ba = oper_func(dest_ba, src_ba)

    key_space[destkey] = RedisStringObject(dest_ba.tobytes())
    return len(key_space[destkey].value)


@server.command('bitops', nargs=nargs_greater_equal(2))
def bitops_handler(argv):
    '''
    Return the position of the first bit set to 1 or 0 in a string.

    The position is returned thinking at the string as an array of bits from left to right where the first
    byte most significant bit is at position 0, the second byte most significant big is at position 8 and
    so forth.

    The same bit position convention is followed by GETBIT and SETBIT.

    By default all the bytes contained in the string are examined. It is possible to look for bits only in
    a specified interval passing the additional arguments start and end (it is possible to just pass start,
    the operation will assume that the end if the last byte of the string. However there are semantical
    differences as explained later). The range is interpreted as a range of bytes and not a range of bits,
    so start=0 and end=2 means to look at the first three bytes.

    Note that bit positions are returned always as absolute values starting from bit zero even when start
    and end are used to specify a range.

    Like for the GETRANGE command start and end can contain negative values in order to index bytes starting
    from the end of the string, where -1 is the last byte, -2 is the penultimate, and so forth.

    Non-existent keys are treated as empty strings.

    ..code ::
        BITPOS key bit [start] [end]

    :return: The command returns the position of the first bit set to 1 or 0 according to the request.

             If we look for set bits (the bit argument is 1) and the string is empty or composed of just zero
             bytes, -1 is returned.

             If we look for clear bits (the bit argument is 0) and the string only contains bit set to 1, the
             function returns the first bit not part of the string on the right. So if the string is tree bytes
             set to the value 0xff the command BITPOS key 0 will return 24, since up to bit 23 all the bits are 1.

             Basically the function consider the right of the string as padded with zeros if you look for clear
             bits and specify no range or the start argument only.

             However this behavior changes if you are looking for clear bits and specify a range with both start
             and end. If no clear bit is found in the specified range, the function returns -1 as the user
             specified a clear range and there are no 0 bits in that range.
    :rtype: int

    '''


@server.command('set', nargs=nargs_greater_equal(2))
def set_handler(argv):
    '''
    Set the string value of a key

    .. code::
        SET key value [EX seconds] [PX milliseconds] [NX|XX]

    :param EX: Set the specified expire time, in seconds.
    :param PX: Set the specified expire time, in milliseconds.
    :param NX: Only set the key if it does not already exist.
    :param XX: Only set the key if it already exist.

    '''

    key, value = argv[1], argv[2]
    expire_time = None
    nx = False
    xx = False

    cur_index = 3
    while cur_index < len(argv):
        argname = argv[cur_index].lower()
        if argname == b'ex':
            if cur_index == len(argv) - 1:
                abort(message='syntax error')
            if expire_time is None:
                expire_time = time.time()
            cur_index += 1
            try:
                expire_time += int(argv[cur_index])
            except:
                abort(message='syntax error')
        elif argname == b'px':
            if cur_index == len(argv) - 1:
                abort(message='syntax error')
            if expire_time is None:
                expire_time = time.time()
            cur_index += 1
            try:
                expire_time += int(argv[cur_index]) / 1000.0
            except:
                abort(message='syntax error')
        elif argname == b'nx':
            nx = True
        elif argname == b'xx':
            xx = True
        else:
            abort(message='syntax error')
        cur_index += 1

    if nx and xx:
        abort(message='syntax error')

    if nx and key in key_space:
        return None
    if xx and key not in key_space:
        return None

    key_space[key] = RedisStringObject(value, expire_time=expire_time)
    return True


@server.command('setbit', nargs=3)
def setbit_handler(argv):
    '''
    Sets or clears the bit at offset in the string value stored at key.

    The bit is either set or cleared depending on value, which can be either 0 or 1.
    When key does not exist, a new string value is created. The string is grown to make
    sure it can hold a bit at offset. The offset argument is required to be greater than
    or equal to 0, and smaller than 232 (this limits bitmaps to 512MB). When the string
    at key is grown, added bits are set to 0.

    .. code::
        SETBIT key offset value

    '''

    key, offset, value = argv[1], argv[2], argv[3]
    if key in key_space and not isinstance(key_space[key], RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        offset = int(offset)
        value = int(value)
    except ValueError:
        abort(message='bit offset is not an integer or out of range')

    ba = bitarray.bitarray()

    if key in key_space:
        if not isinstance(key_space[key], RedisStringObject):
            abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
        ba.frombytes(key_space[key].value)
    else:
        key_space[key] = RedisStringObject()

    if len(ba) < offset:
        ba.extend([0] * (offset - len(ba) + 1))

    ba[offset] = value
    key_space[key].value = ba.tobytes()
    return True


@server.command('setex', nargs=3)
def setex_handler(argv):
    '''
    Set key to hold the string value and set key to timeout after a given number of seconds.
    This command is equivalent to executing the following commands:

    .. code::
        SETEX key seconds value

    '''

    key, seconds, value = argv[1], argv[2], argv[3]
    try:
        seconds = int(seconds)
        if seconds <= 0:
            abort(message='invalid expire time in SETEX')
    except ValueError:
        abort(message='value is not an integer or out of range')

    key_space[key] = RedisStringObject(value, expire_time=time.time() + seconds)
    return True


@server.command('setnx', nargs=2)
def setnx_handler(argv):
    '''
    Set key to hold string value if key does not exist. In that case, it is equal to SET.
    When key already holds a value, no operation is performed. SETNX is short for "SET if N ot e X ists".

    .. code::
        SETNX key value

    :return: 1 if key was set, otherwise 0
    :rtype: int

    '''

    key, value = argv[1], argv[2]
    if key in key_space:
        return 0
    key_space[key] = RedisStringObject(value)
    return 1


@server.command('setrange', nargs=3)
def setrange_handler(argv):
    '''
    Overwrites part of the string stored at key, starting at the specified offset, for the entire
    length of value. If the offset is larger than the current length of the string at key, the string
    is padded with zero-bytes to make offset fit. Non-existing keys are considered as empty strings,
    so this command will make sure it holds a string large enough to be able to set value at offset.

    Note that the maximum offset that you can set is 229 -1 (536870911), as Redis Strings are limited
    to 512 megabytes. If you need to grow beyond this size, you can use multiple keys.

    .. code::
        SETRANGE key offset value

    :return: the length of the string after it was modified by the command.
    :rtype: int

    '''

    key, offset, value = argv[1], argv[2], argv[3]
    try:
        offset = int(offset)
    except ValueError:
        abort(message='value is not an integer or out of range')

    if key not in key_space:
        obj = RedisStringObject()
    else:
        obj = key_space[key]
        if not isinstance(obj, RedisStringObject):
            abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    if len(obj.value) < offset:
        obj.value += bytes(offset - len(obj.value)) + value
    else:
        obj.value = obj.value[0:offset + 1] + value

    key_space[key] = obj
    return len(obj.value)


@server.command('get', nargs=1)
def get_handler(argv):
    '''
    Get the value of key. If the key does not exist the special value nil is returned.
    An error is returned if the value stored at key is not a string, because GET only handles string values.

    .. code::
        GET key

    '''

    key = argv[1]
    if key not in key_space:
        return None

    if key_space[key].expired():
        del key_space[key]
        return None

    if not isinstance(key_space[key], RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
    return key_space[key].value


import bitarray


@server.command('getbit', nargs=2)
def getbit_handler(argv):
    '''
    Returns the bit value at offset in the string value stored at key.

    When offset is beyond the string length, the string is assumed to be a contiguous space with 0 bits.
    When key does not exist it is assumed to be an empty string, so offset is always out of range and the
    value is also assumed to be a contiguous space with 0 bits.

    .. code::
        GETBIT key offset

    '''

    key, offset = argv[1], argv[2]

    try:
        offset = int(offset)
    except ValueError:
        abort(message='bit offset is not an integer or out of range')

    if key not in key_space:
        return 0

    if not isinstance(key_space[key], RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    ba = bitarray.bitarray()
    ba.frombytes(key_space[key].value)

    try:
        return int(ba[offset])
    except IndexError:
        return 0


@server.command('getrange', nargs=3)
def getrange_handler(argv):
    '''
    Returns the substring of the string value stored at key, determined by the offsets start and end
    (both are inclusive). Negative offsets can be used in order to provide an offset starting from the
    end of the string. So -1 means the last character, -2 the penultimate and so forth.

    The function handles out of range requests by limiting the resulting range to the actual length of
    the string.

    .. code::
        GETRANGE key start end

    '''

    key, start, end = argv[1], argv[2], argv[3]

    try:
        start = int(start)
        end = int(end)
    except ValueError:
        abort(message='value is not an integer or out of range')

    if key not in key_space:
        return ""

    if not isinstance(key_space[key], RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    if end == -1:
        end = len(key_space[key].value)
    return key_space[key].value[start:end + 1]


@server.command('getset', nargs=2)
def getset_handler(argv):
    '''
    Atomically sets key to value and returns the old value stored at key. Returns an error when key
    exists but does not hold a string value.

    .. code::
        GETSET key value

    '''

    key, value = argv[1], argv[2]

    if key in key_space and not isinstance(key_space[key], RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    if key in key_space:
        orig_value = key_space[key].value
        key_space[key].value = value
    else:
        orig_value = None
        key_space[key] = RedisStringObject(value)

    return orig_value