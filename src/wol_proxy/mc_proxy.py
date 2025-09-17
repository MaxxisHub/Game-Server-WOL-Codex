import asyncio
import json
from typing import Callable, Optional
from .util import log


def _read_varint_from_stream(reader: asyncio.StreamReader) -> asyncio.Future:
    async def _inner():
        num = 0
        num_read = 0
        while True:
            b = await reader.readexactly(1)
            val = b[0]
            num |= (val & 0x7F) << (7 * num_read)
            num_read += 1
            if num_read > 5:
                raise ValueError("VarInt too big")
            if (val & 0x80) == 0:
                break
        return num
    return asyncio.ensure_future(_inner())


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        temp = value & 0x7F
        value >>= 7
        if value != 0:
            temp |= 0x80
        out.append(temp)
        if value == 0:
            break
    return bytes(out)


def _encode_string(s: str) -> bytes:
    data = s.encode("utf-8")
    return _encode_varint(len(data)) + data


class MCProxy:
    def __init__(self, bind_ip: str, port: int,
                 get_status: Callable[[int], dict],
                 on_join_attempt: Callable[[str], None]):
        self.bind_ip = bind_ip
        self.port = port
        self.get_status = get_status
        self.on_join_attempt = on_join_attempt
        self._server: Optional[asyncio.base_events.Server] = None

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, host=self.bind_ip, port=self.port)
        log(f"MC proxy listening on {self.bind_ip}:{self.port}")

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            log("MC proxy stopped")
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        try:
            # Handshake
            pkt_len = await _read_varint_from_stream(reader)
            data = await reader.readexactly(pkt_len)
            # Parse handshake
            # data: varint packet id (0x00), varint protocol version, string server addr, unsigned short port, varint next state
            buf = memoryview(data)
            # read varint packet id
            i = 0
            def read_varint_from(buf, i):
                num = 0
                num_read = 0
                while True:
                    val = buf[i]
                    i += 1
                    num |= (val & 0x7F) << (7 * num_read)
                    num_read += 1
                    if num_read > 5:
                        raise ValueError("VarInt too big")
                    if (val & 0x80) == 0:
                        break
                return num, i

            def read_string_from(buf, i):
                ln, i = read_varint_from(buf, i)
                s = bytes(buf[i:i+ln]).decode('utf-8', errors='replace')
                i += ln
                return s, i

            pkt_id, i = read_varint_from(buf, i)
            if pkt_id != 0x00:
                raise ValueError("Unexpected first packet id")
            proto_ver, i = read_varint_from(buf, i)
            _, i = read_string_from(buf, i)  # server address
            if i + 2 > len(buf):
                return
            i += 2  # skip server port
            next_state, i = read_varint_from(buf, i)

            if next_state == 1:
                # Status flow
                # Read status request packet (should be id=0x00 with empty payload)
                req_len = await _read_varint_from_stream(reader)
                if req_len:
                    await reader.readexactly(req_len)
                # Build status response
                status = self.get_status(proto_ver)
                resp_json = json.dumps(status, ensure_ascii=False)
                payload = _encode_varint(0x00) + _encode_string(resp_json)
                pkt = _encode_varint(len(payload)) + payload
                writer.write(pkt)
                await writer.drain()
                # Handle ping (id=0x01) echo
                try:
                    pkt_len2 = await _read_varint_from_stream(reader)
                    data2 = await reader.readexactly(pkt_len2)
                    if len(data2) >= 9 and data2[0] == 0x01:
                        # Echo back
                        writer.write(_encode_varint(len(data2)) + data2)
                        await writer.drain()
                except asyncio.IncompleteReadError:
                    pass
            elif next_state == 2:
                # Login flow: trigger join attempt
                # Read login start (id=0x00), ignore username
                try:
                    _ = await _read_varint_from_stream(reader)
                except asyncio.IncompleteReadError:
                    pass
                # Trigger WOL
                self.on_join_attempt(f"login from {addr}")
                # Send disconnect with message
                msg_json = json.dumps({"text": "Server is starting please try again in 60 seconds"}, ensure_ascii=False)
                payload = _encode_varint(0x00) + _encode_string(msg_json)
                pkt = _encode_varint(len(payload)) + payload
                writer.write(pkt)
                await writer.drain()
            else:
                # Unknown state, close
                pass
        except Exception as e:
            log(f"MC client error {addr}: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
