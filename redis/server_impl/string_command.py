
from redis.server import current_server as server
from redis.common.objects import RedisStringObject
from redis.common.utils import abort, close_connection
from redis.common.utils import nargs_greater_equal
from redis.common.utils import group_iter, get_object
import time
import bitarray
from decimal import InvalidOperation, Decimal


@server.command('bitcount', nargs=nargs_greater_equal(1))
def bitcount_handler(client, argv):
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

    try:
        obj = get_object(client.db, key, RedisStringObject)
    except KeyError:
        return 0
    except ValueError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    if end == -1:
        end = None
    elif end is not None:
        end += 1

    ba = bitarray.bitarray()
    ba.frombytes(obj.get_bytes()[start:end])
    return ba.count()


@server.command('bitop', nargs=nargs_greater_equal(3))
def bitop_handler(client, argv):
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
    print(operation, destkey, keys)
    if operation not in (b'AND', b'OR', b'XOR', b'NOT'):
        abort(message='Don\'t know what to do for "bitop"')

    if operation == b'NOT':
        if len(keys) > 1:
            abort(message='BITOP NOT must be called with a single source key.')

        try:
            obj = get_object(client.db, keys[0], RedisStringObject)
        except KeyError:
            return 0
        except TypeError:
            abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

        ba = bitarray.bitarray()
        ba.frombytes(obj.get_bytes())
        ba.invert()
        client.db.key_space[destkey] = RedisStringObject(ba.tobytes())
        return len(client.db.key_space[destkey].value)

    if operation == b'AND':
        oper_func = lambda a, b: a & b
    elif operation == b'OR':
        oper_func = lambda a, b: a | b
    elif operation == b'XOR':
        oper_func = lambda a, b: a ^ b

    dest_ba = bitarray.bitarray()
    try:
        obj = get_object(client.db, keys[0], RedisStringObject)
        dest_ba.frombytes(obj.get_bytes())
    except KeyError:
        pass
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    for key in keys[1:]:
        try:
            obj = get_object(client.db, key, RedisStringObject)
            src_ba = bitarray.bitarray()
            src_ba.frombytes(obj.get_bytes())

            if len(src_ba) > len(dest_ba):
                dest_ba = bitarray.bitarray('0' * (len(src_ba) - len(dest_ba))) + dest_ba
            elif len(dest_ba) > len(src_ba):
                src_ba = bitarray.bitarray('0' * (len(dest_ba) - len(src_ba))) + src_ba
        except KeyError:
            src_ba = bitarray.bitarray('0' * len(dest_ba))
        except TypeError:
            abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

        dest_ba = oper_func(dest_ba, src_ba)

    client.db.key_space[destkey] = RedisStringObject(dest_ba.tobytes())
    return len(client.db.key_space[destkey].get_bytes())


@server.command('bitpos', nargs=nargs_greater_equal(2))
def bitpos_handler(client, argv):
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

    key, bit = argv[1], argv[2]
    try:
        bit = int(bit.decode())
        if bit not in (0, 1):
            abort(message='The bit argument must be 1 or 0.')
    except ValueError:
        abort(message='value is not an integer or out of range')

    if len(argv) > 5:
        abort(message='syntax error')
    try:
        start = int(argv[3])
    except ValueError:
        abort(message='value is not an integer or out of range')
    except IndexError:
        start = None

    try:
        end = int(argv[4])
    except ValueError:
        abort(message='value is not an integer or out of range')
    except IndexError:
        end = None

    begin_pos = 0
    try:
        obj = get_object(client.db, key, RedisStringObject)
        ba = bitarray.bitarray()
        if start is not None:
            if start < 0:
                start = len(obj.get_bytes()) + start
            begin_pos = start * 8

        if end is not None:
            if end < 0:
                end = len(obj.get_bytes()) + end
            end += 1

        ba.frombytes(obj.get_bytes()[start:end])
    except KeyError:
        ba = bitarray.bitarray(b'0')
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    pos = ba.search(bitarray.bitarray(str(bit)), 1)
    if len(pos) == 0:
        return -1
    else:
        return pos[0] + begin_pos


@server.command('set', nargs=nargs_greater_equal(2))
def set_handler(client, argv):
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

    try:
        get_object(client.db, key)
        if nx:
            return None
    except KeyError:
        if xx:
            return None

    try:
        value = int(value)
    except ValueError:
        pass
    client.db.key_space[key] = RedisStringObject(value, expire_time=expire_time)
    return True


@server.command('setbit', nargs=3)
def setbit_handler(client, argv):
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
    if key in client.db.key_space and not isinstance(client.db.key_space[key], RedisStringObject):
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        offset = int(offset)
        value = int(value)
    except ValueError:
        abort(message='bit offset is not an integer or out of range')

    ba = bitarray.bitarray()

    try:
        obj = get_object(client.db, key, RedisStringObject)
        ba.frombytes(obj.get_bytes())
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
    except KeyError:
        pass

    if len(ba) < offset:
        ba.extend([0] * (offset - len(ba) + 1))

    ba[offset] = value
    client.db.key_space[key].value = ba.tobytes()
    return True


@server.command('setex', nargs=3)
def setex_handler(client, argv):
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

    client.db.key_space[key] = RedisStringObject(value, expire_time=time.time() + seconds)
    return True


@server.command('setnx', nargs=2)
def setnx_handler(client, argv):
    '''
    Set key to hold string value if key does not exist. In that case, it is equal to SET.
    When key already holds a value, no operation is performed. SETNX is short for "SET if N ot e X ists".

    .. code::
        SETNX key value

    :return: 1 if key was set, otherwise 0
    :rtype: int

    '''

    key, value = argv[1], argv[2]
    try:
        get_object(client.db, key)
        return 0
    except KeyError:
        client.db.key_space[key] = RedisStringObject(value)
    return 1


@server.command('setrange', nargs=3)
def setrange_handler(client, argv):
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

    try:
        obj = get_object(client.db, key, RedisStringObject)
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
    except KeyError:
        obj = RedisStringObject()

    stor_value = obj.get_bytes()
    if len(stor_value) < offset:
        stor_value += bytes(offset - len(stor_value)) + value
    else:
        stor_value = stor_value[0:offset + 1] + value

    obj.value = stor_value
    client.db.key_space[key] = obj
    return len(stor_value)


@server.command('get', nargs=1)
def get_handler(client, argv):
    '''
    Get the value of key. If the key does not exist the special value nil is returned.
    An error is returned if the value stored at key is not a string, because GET only handles string values.

    .. code::
        GET key

    '''

    key = argv[1]
    try:
        obj = get_object(client.db, key, RedisStringObject)
        return obj
    except KeyError:
        return None
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')


@server.command('getbit', nargs=2)
def getbit_handler(client, argv):
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

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
        ba = bitarray.bitarray()
        ba.frombytes(obj.get_bytes())
        return int(ba[offset])
    except KeyError:
        return None
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')
    except IndexError:
        return 0


@server.command('getrange', nargs=3)
def getrange_handler(client, argv):
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

    try:
        obj = get_object(client.db, key, type=RedisStringObject)

    except KeyError:
        return b''
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    length = len(obj)
    if start < 0:
        start = length + start
    if end < 0:
        end = length + end
    return obj.get_range(start, end)


@server.command('getset', nargs=2)
def getset_handler(client, argv):
    '''
    Atomically sets key to value and returns the old value stored at key. Returns an error when key
    exists but does not hold a string value.

    .. code::
        GETSET key value

    '''

    key, value = argv[1], argv[2]

    try:
        value = int(value)
    except ValueError:
        pass

    try:
        obj = get_object(client.db, key, type=RedisStringObject)

        orig_value = obj.get_bytes()
        obj.value = value
    except KeyError:
        orig_value = None
        client.db.key_space[key] = RedisStringObject(value)
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    return RedisStringObject(orig_value)


@server.command('decr', nargs=1)
def decr_handler(client, argv):
    '''
    Decrements the number stored at key by one. If the key does not exist, it is set to 0 before
    performing the operation. An error is returned if the key contains a value of the wrong type
    or contains a string that can not be represented as integer. This operation is limited to 64
    bit signed integers.

    See INCR for extra information on increment/decrement operations.

    .. code::
        DECR key

    :return: the value of key after the decrement
    :rtype: int

    '''
    key = argv[1]

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
        value = obj.get_integer()
    except KeyError:
        value = 0
        obj = RedisStringObject(value)
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        value = obj.get_integer()
    except ValueError:
        abort(message='value is not an integer or out of range')

    value -= 1

    obj.value = value
    # client.db.key_space[key] = obj
    return obj


@server.command('decrby', nargs=2)
def decrby_handler(client, argv):
    '''
    Decrements the number stored at key by decrement. If the key does not exist, it is set to 0
    before performing the operation. An error is returned if the key contains a value of the wrong
    type or contains a string that can not be represented as integer. This operation is limited to
    64 bit signed integers.

    See INCR for extra information on increment/decrement operations.

    .. code::
        DECRBY key decrement

    :return: the value of key after the decrement
    :rtype: int

    '''

    key, decrement = argv[1], argv[2]

    try:
        decrement = int(decrement)
    except ValueError:
        abort(message='value is not an integer or out of range')

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
        value = obj.get_integer()
    except KeyError:
        value = 0
        obj = RedisStringObject(value)
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        value = obj.get_integer()
    except ValueError:
        abort(message='value is not an integer or out of range')

    value -= decrement

    obj.value = value
    # client.db.key_space[key] = obj
    return obj


@server.command('incr', nargs=1)
def incr_handler(client, argv):
    '''
    Increments the number stored at key by one. If the key does not exist, it is set to 0 before
    performing the operation. An error is returned if the key contains a value of the wrong type or
    contains a string that can not be represented as integer. This operation is limited to 64 bit
    signed integers.

    Note: this is a string operation because Redis does not have a dedicated integer type. The string
    stored at the key is interpreted as a base-10 64 bit signed integer to execute the operation.

    Redis stores integers in their integer representation, so for string values that actually hold an
    integer, there is no overhead for storing the string representation of the integer.

    .. code::
        INCR key

    :return: the value of key after the increment
    :rtype: int

    '''
    key = argv[1]

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
        value = obj.get_integer()
    except KeyError:
        value = 0
        obj = RedisStringObject(value)
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        value = obj.get_integer()
    except ValueError:
        abort(message='value is not an integer or out of range')

    value += 1

    obj.value = value
    client.db.key_space[key] = obj
    return obj


@server.command('incrby', nargs=2)
def incrby_handler(client, argv):
    '''
    Increments the number stored at key by increment. If the key does not exist, it is set to 0 before
    performing the operation. An error is returned if the key contains a value of the wrong type or
    contains a string that can not be represented as integer. This operation is limited to 64 bit signed
    integers.

    See INCR for extra information on increment/decrement operations.

    .. code::
        INCRBY key increment

    :return: the value of key after the increment
    :rtype: int
    '''

    key, increment = argv[1], argv[2]

    try:
        increment = int(increment)
    except ValueError:
        abort(message='value is not an integer or out of range')

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
        value = obj.get_integer()
    except KeyError:
        value = 0
        obj = RedisStringObject(value)
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        value = obj.get_integer()
    except ValueError:
        abort(message='value is not an integer or out of range')

    value += increment

    obj.value = value
    client.db.key_space[key] = obj
    return obj


@server.command('incrbyfloat', nargs=2)
def incrbyfloat_handler(client, argv):
    '''
    Increment the string representing a floating point number stored at key by the specified increment.
    If the key does not exist, it is set to 0 before performing the operation. An error is returned if
    one of the following conditions occur:

    * The key contains a value of the wrong type (not a string).
    * The current key content or the specified increment are not parsable as a double precision floating
      point number.

    If the command is successful the new incremented value is stored as the new value of the key (replacing
    the old one), and returned to the caller as a string.

    Both the value already contained in the string key and the increment argument can be optionally provided
    in exponential notation, however the value computed after the increment is stored consistently in the
    same format, that is, an integer number followed (if needed) by a dot, and a variable number of digits
    representing the decimal part of the number. Trailing zeroes are always removed.

    The precision of the output is fixed at 17 digits after the decimal point regardless of the actual internal
    precision of the computation.

    .. code::
        INCRBYFLOAT key increment

    :return: the value of key after the increment.
    :rtype: bytes

    '''

    key, increment = argv[1], argv[2]

    try:
        increment = Decimal(increment.decode())
    except InvalidOperation:
        abort(message='value is not a valid float')

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
        value = obj.get_integer()
    except KeyError:
        value = 0
        obj = RedisStringObject()
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    try:
        value = obj.get_decimal()
    except InvalidOperation:
        abort(message='value is not a valid float')

    value += increment

    obj.value = value
    client.db.key_space[key] = obj
    return obj


@server.command('strlen', nargs=1)
def strlen_handler(client, argv):
    '''
    Returns the length of the string value stored at key. An error is returned when key holds a non-string value.

    .. code::
        STRLEN key

    :return: the length of the string at key, or 0 when key does not exist.
    :rtype: int

    '''

    key = argv[1]

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
    except KeyError:
        return 0
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    return len(obj.get_bytes())


@server.command('append', nargs=2)
def append_handler(client, argv):
    '''
    If key already exists and is a string, this command appends the value at the end of the string.
    If key does not exist it is created and set as an empty string, so APPEND will be similar to SET
    in this special case.

    .. code::
        APPEND key value

    :return: the length of the string after the append operation.
    :rtype: int

    '''

    key, value = argv[1], argv[2]

    try:
        obj = get_object(client.db, key, type=RedisStringObject)
    except KeyError:
        length = len(value)
        try:
            value = int(value)
        except ValueError:
            pass
        client.db.key_space[key] = RedisStringObject(value)
        return length
    except TypeError:
        abort(errtype='WRONGTYPE', message='Operation against a key holding the wrong kind of value')

    obj.value = obj.get_bytes() + value

    return len(obj.value)


@server.command('mset', nargs=nargs_greater_equal(2))
def mset_handler(client, argv):
    '''
    Sets the given keys to their respective values. MSET replaces existing values with new values,
    just as regular SET. See MSETNX if you don't want to overwrite existing values.

    MSET is atomic, so all given keys are set at once. It is not possible for clients to see that
    some of the keys were updated while others are unchanged.

    .. code::
        MSET key value [key value ...]

    '''

    if len(argv) & 1 == 0:
        abort(message='wrong number of arguments for MSET')

    for key, value in group_iter(argv[1:], n=2):
        client.db.key_space[key] = RedisStringObject(value=value)

    return True


@server.command('msetnx', nargs=nargs_greater_equal(2))
def msetnx_handler(client, argv):
    '''
    Sets the given keys to their respective values. MSETNX will not perform any operation at all even
    if just a single key already exists.

    Because of this semantic MSETNX can be used in order to set different keys representing different
    fields of an unique logic object in a way that ensures that either all the fields or none at all
    are set.

    MSETNX is atomic, so all given keys are set at once. It is not possible for clients to see that some
    of the keys were updated while others are unchanged.

    .. code::
        MSETNX key value [key value ...]

    :return: 1 if the all the keys were set. 0 if no key was set (at least one key already existed).
    :rtype: int

    '''

    if len(argv) & 1 == 0:
        abort(message='wrong number of arguments for MSET')

    all_set = True
    for key, value in group_iter(argv[1:], n=2):
        try:
            get_object(client.db, key)
            all_set = False
            break
        except KeyError:
            pass

    if all_set:
        for key, value in group_iter(argv[1:], n=2):
            client.db.key_space[key] = RedisStringObject(value=value)

    return int(all_set)


@server.command('mget', nargs=nargs_greater_equal(1))
def mget_handler(client, argv):
    '''
    Returns the values of all specified keys. For every key that does not hold a string value or does
    not exist, the special value nil is returned. Because of this, the operation never fails.

    .. code::
        MGET key [key ...]

    :return: list of values at the specified keys.
    :rtype: list

    '''

    result = []
    for key in argv[1:]:
        try:
            obj = get_object(client.db, key, RedisStringObject)
            result.append(obj)
        except (TypeError, KeyError):
            result.append(None)

    return result
