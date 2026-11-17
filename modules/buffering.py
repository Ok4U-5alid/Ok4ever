#tcpdump -i lo -nn -X port 8080
import socket
import time

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# عطّل Nagle (اختياري، أحيانًا تفعيله يساعد الدمج حسب السيناريو)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)

s.connect(("127.0.0.1", 8080))

part1 = b"GET / HTTP/1.1\r\nHost: localhost\r\n"
part2 = b"User-Agent: test\r\n\r\n"

# إرسال الجزأين بسرعة بدون flush
s.sendall(part1)
s.sendall(part2)

time.sleep(1)
s.close()


def process(text: str) -> str:
    """Module pre-processor for ai_server."""
    return text
