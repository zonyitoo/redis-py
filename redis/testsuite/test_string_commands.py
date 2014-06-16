
from redis.server_impl import server

c = server.get_test_client()


def test_set():
    assert c.execute(b'SET hello world\r\n') == b'+OK\r\n'
    assert c.execute(b'SET key "\\x80"\r\n') == b'+OK\r\n'


def test_get():
    assert c.execute(b'GET hello\r\n') == b'$5\r\nworld\r\n'
    assert c.execute(b'GET key\r\n') == b'$1\r\n\x80\r\n'


def test_bitcount():
    assert c.execute(b'SET hello world\r\n') == b'+OK\r\n'
    assert c.execute(b'BITCOUNT hello\r\n') == b':23\r\n'


def test_bitop():
    assert c.execute(b'SET key1 "\\x80"\r\n') == b'+OK\r\n'
    assert c.execute(b'SET key2 "\\x40"\r\n') == b'+OK\r\n'
    assert c.execute(b'BITOP AND dest key1 key2\r\n') == b':1\r\n'
    assert c.execute(b'GET dest\r\n') == b'$1\r\n\x00\r\n'
    assert c.execute(b'BITOP OR dest key1 key2\r\n') == b':1\r\n'
    assert c.execute(b'GET dest\r\n') == b'$1\r\n\xC0\r\n'
    assert c.execute(b'BITOP XOR dest key1 key2\r\n') == b':1\r\n'
    assert c.execute(b'GET dest\r\n') == b'$1\r\n\xC0\r\n'
    assert c.execute(b'BITOP NOT dest key1\r\n') == b':1\r\n'
    assert c.execute(b'GET dest\r\n') == b'$1\r\n\x7F\r\n'

    assert c.execute(b'SET key3 "\\x80\\x00"\r\n') == b'+OK\r\n'
    assert c.execute(b'BITOP AND dest key3 key1\r\n') == b':2\r\n'
    assert c.execute(b'GET dest\r\n') == b'$2\r\n\x00\x00\r\n'