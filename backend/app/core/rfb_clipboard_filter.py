"""Protocol-level enforcement of a session's ClipboardMode on the RFB
byte stream app/api/display.py relays between the user's browser and the
sandbox's VNC server.

This is deliberately *not* a full RFB/VNC protocol parser — see
docs/policies.md's "Clipboard" section for why that would be out of
scope, and the design this module implements instead.

Client→Server direction (ClientCutText, i.e. "paste local clipboard into
the sandbox"): the message set noVNC (the only client this relay talks
to, frontend/user/src/pages/SecureBrowser.tsx) ever sends is small and
fully enumerable with fixed or trivially length-prefixed framing — see
the message builders in @novnc/novnc's core/rfb.js. ClientToServerFilter
below always parses this direction and can drop ClientCutText outright.

Server→Client direction (ServerCutText): this rides in the same message
stream as FramebufferUpdate, whose rectangle payload length depends on
the negotiated pixel encoding (Raw, CopyRect, RRE, Hextile, Tight, ZRLE,
...). Reliably finding message boundaries for the *general* case would
mean reimplementing those encodings' framing — real work, real risk of
silently desyncing the video stream, and exactly what this project's own
brief says not to do. Instead: when (and only when) a session's resolved
ClipboardMode requires blocking ServerCutText, ClientToServerFilter
rewrites the client's own SetEncodings message in flight to advertise
only Raw and CopyRect — pixel encodings with fixed, computable framing —
before it reaches the sandbox's VNC server. ServerToClientFilter then
only ever needs to understand Raw/CopyRect rectangles to track message
boundaries in the FramebufferUpdate stream and drop ServerCutText
messages selectively.

Cost of that trade-off, real and documented rather than silent: sessions
with ServerCutText blocked (ClipboardMode NONE or LOCAL_TO_REMOTE) lose
server-side compression (more bandwidth) and remote cursor-shape updates
(noVNC falls back to a local pointer) for the lifetime of the session.
Sessions where ServerCutText is allowed (REMOTE_TO_LOCAL, BIDIRECTIONAL_
TEXT — the unconfigured default) are completely unaffected: no rewrite,
no server-stream parsing, pure byte passthrough exactly as before this
module existed.

Fail-closed: any byte sequence that doesn't match the bounded framing
this module understands raises RfbProtocolError. The caller (display.py)
must stop relaying and tear the connection down rather than guess — a
misparse here could silently forward a clipboard message that should
have been blocked, or corrupt the video/input stream.

Known residual risk, not eliminated by this design: this module can only
block messages it recognizes as ClientCutText/ServerCutText. It does not
defend against a compromised or malicious VNC server implementation that
declines to honor the restricted SetEncodings list — that would surface
as an RfbProtocolError (connection torn down) rather than a silent leak,
because ServerToClientFilter only ever accepts Raw/CopyRect rectangles
once restricted. It does not (and cannot, at this layer) prevent a
sandboxed application from exfiltrating clipboard-like data through some
channel that isn't RFB CutText at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import ClipboardMode

# Raw, CopyRect — see @novnc/novnc/core/encodings.js. The only two pixel
# encodings this module knows how to compute rectangle lengths for
# without decoding pixel data.
_FORCED_ENCODINGS = (1, 0)


class RfbProtocolError(RuntimeError):
    """A byte sequence didn't match the bounded RFB message framing this
    module understands. Callers must stop relaying bytes in that
    direction and close the connection — never guess and keep forwarding.
    """


@dataclass
class ClipboardEnforcement:
    block_client_to_server: bool  # drop ClientCutText (browser -> sandbox)
    block_server_to_client: bool  # drop ServerCutText (sandbox -> browser)

    @property
    def restrict_server_encodings(self) -> bool:
        # Only needed to make ServerToClientFilter's rectangle-boundary
        # tracking tractable — see module docstring. Irrelevant (and
        # skipped) when ServerCutText isn't being blocked anyway.
        return self.block_server_to_client


def enforcement_for_mode(mode: ClipboardMode) -> ClipboardEnforcement:
    return ClipboardEnforcement(
        block_client_to_server=mode not in (ClipboardMode.LOCAL_TO_REMOTE, ClipboardMode.BIDIRECTIONAL_TEXT),
        block_server_to_client=mode not in (ClipboardMode.REMOTE_TO_LOCAL, ClipboardMode.BIDIRECTIONAL_TEXT),
    )


class _PixelFormatTracker:
    """Shared between one session's two filter instances. Server->client
    Raw-rectangle lengths need the negotiated bytes-per-pixel, which is
    only ever set by the client's own SetPixelFormat message (noVNC always
    sends this during connection setup, before requesting any framebuffer
    update) — never guessed or defaulted.
    """

    def __init__(self) -> None:
        self.bytes_per_pixel: int | None = None


def build_filters(mode: ClipboardMode) -> tuple[ClientToServerFilter, ServerToClientFilter]:
    enforcement = enforcement_for_mode(mode)
    pixel_format = _PixelFormatTracker()
    client_filter = ClientToServerFilter(
        block_cut_text=enforcement.block_client_to_server,
        restrict_server_encodings=enforcement.restrict_server_encodings,
        pixel_format=pixel_format,
    )
    server_filter = ServerToClientFilter(
        block_cut_text=enforcement.block_server_to_client,
        restrict_encodings=enforcement.restrict_server_encodings,
        pixel_format=pixel_format,
    )
    return client_filter, server_filter


class ClientToServerFilter:
    """Parses the bounded set of client->server RFB messages noVNC ever
    sends. Always active (cheap, fully enumerable framing) — even when
    nothing needs blocking, so behavior stays uniform; the no-op fast path
    below keeps that case a pure passthrough with zero added latency.
    """

    def __init__(self, *, block_cut_text: bool, restrict_server_encodings: bool, pixel_format: _PixelFormatTracker) -> None:
        self._block_cut_text = block_cut_text
        self._restrict = restrict_server_encodings
        self._pixel_format = pixel_format
        self._buf = bytearray()
        self.blocked_once = False

    def feed(self, data: bytes) -> bytes:
        if not self._block_cut_text and not self._restrict:
            # Nothing this filter would ever change — BIDIRECTIONAL_TEXT
            # or REMOTE_TO_LOCAL, the common/default case. Skip parsing
            # entirely: pure passthrough, identical to pre-existing
            # behavior, no buffering latency added.
            return data

        self._buf.extend(data)
        out = bytearray()
        while True:
            msg = self._take_one()
            if msg is None:
                break
            out.extend(msg)
        return bytes(out)

    def _take_one(self) -> bytes | None:
        buf = self._buf
        if not buf:
            return None
        msg_type = buf[0]

        if msg_type == 0:  # SetPixelFormat: type(1) + pad(3) + 16-byte struct
            if len(buf) < 20:
                return None
            bpp = buf[4]
            self._pixel_format.bytes_per_pixel = bpp // 8
            return self._consume(20)

        if msg_type == 2:  # SetEncodings: type(1) + pad(1) + count(2) + 4*count
            if len(buf) < 4:
                return None
            count = int.from_bytes(buf[2:4], "big")
            total = 4 + 4 * count
            if len(buf) < total:
                return None
            raw = self._consume(total)
            if self._restrict:
                return _build_set_encodings(_FORCED_ENCODINGS)
            return raw

        if msg_type == 3:  # FramebufferUpdateRequest: 10 bytes fixed
            if len(buf) < 10:
                return None
            return self._consume(10)

        if msg_type == 4:  # KeyEvent: 8 bytes fixed
            if len(buf) < 8:
                return None
            return self._consume(8)

        if msg_type == 5:  # PointerEvent: 6 bytes fixed
            if len(buf) < 6:
                return None
            return self._consume(6)

        if msg_type == 6:  # ClientCutText: type(1)+pad(3)+length(4, signed)+abs(length)
            if len(buf) < 8:
                return None
            length = int.from_bytes(buf[4:8], "big", signed=True)
            total = 8 + abs(length)
            if len(buf) < total:
                return None
            raw = self._consume(total)
            if self._block_cut_text:
                self.blocked_once = True
                return b""
            return raw

        if msg_type == 150:  # EnableContinuousUpdates: 10 bytes fixed
            if len(buf) < 10:
                return None
            return self._consume(10)

        if msg_type == 248:  # ClientFence: type(1)+pad(3)+flags(4)+len(1)+payload
            if len(buf) < 9:
                return None
            payload_len = buf[8]
            total = 9 + payload_len
            if len(buf) < total:
                return None
            return self._consume(total)

        if msg_type == 250:  # XVP: type(1)+pad(1)+ver(1)+op(1)
            if len(buf) < 4:
                return None
            return self._consume(4)

        if msg_type == 251:  # SetDesktopSize: header(8) + 16*num-screens
            if len(buf) < 8:
                return None
            num_screens = buf[6]
            total = 8 + 16 * num_screens
            if len(buf) < total:
                return None
            return self._consume(total)

        if msg_type == 255:  # QEMU extended key event: type(1)+sub-type(1)+...
            if len(buf) < 2:
                return None
            sub_type = buf[1]
            if sub_type != 0:
                raise RfbProtocolError(f"unrecognized QEMU client sub-message type {sub_type}")
            if len(buf) < 12:
                return None
            return self._consume(12)

        raise RfbProtocolError(f"unrecognized client->server RFB message type {msg_type}")

    def _consume(self, n: int) -> bytes:
        raw = bytes(self._buf[:n])
        del self._buf[:n]
        return raw


class ServerToClientFilter:
    """Parses the server->client RFB message stream, but only once
    restrict_encodings is True — see the module docstring for why full
    parsing is only tractable once the client's SetEncodings has been
    forced to Raw/CopyRect. When restrict_encodings is False, feed() is a
    pure byte passthrough: no parsing, no risk, identical to pre-existing
    behavior.
    """

    def __init__(self, *, block_cut_text: bool, restrict_encodings: bool, pixel_format: _PixelFormatTracker) -> None:
        self._block_cut_text = block_cut_text
        self._restrict = restrict_encodings
        self._pixel_format = pixel_format
        self._buf = bytearray()
        self._fbu_rects_remaining = 0
        self.blocked_once = False

    def feed(self, data: bytes) -> bytes:
        if not self._restrict:
            return data

        self._buf.extend(data)
        out = bytearray()
        while True:
            msg = self._take_one()
            if msg is None:
                break
            out.extend(msg)
        return bytes(out)

    def _take_one(self) -> bytes | None:
        if self._fbu_rects_remaining > 0:
            return self._take_rect()

        buf = self._buf
        if not buf:
            return None
        msg_type = buf[0]

        if msg_type == 0:  # FramebufferUpdate: type(1)+pad(1)+num-rects(2), then rects
            if len(buf) < 4:
                return None
            num_rects = int.from_bytes(buf[2:4], "big")
            header = self._consume(4)
            self._fbu_rects_remaining = num_rects
            return header

        if msg_type == 1:  # SetColourMapEntries: type(1)+pad(1)+first(2)+count(2)+6*count
            if len(buf) < 6:
                return None
            num_colours = int.from_bytes(buf[4:6], "big")
            total = 6 + 6 * num_colours
            if len(buf) < total:
                return None
            return self._consume(total)

        if msg_type == 2:  # Bell: 1 byte
            return self._consume(1)

        if msg_type == 3:  # ServerCutText: type(1)+pad(3)+length(4, signed)+abs(length)
            if len(buf) < 8:
                return None
            length = int.from_bytes(buf[4:8], "big", signed=True)
            total = 8 + abs(length)
            if len(buf) < total:
                return None
            raw = self._consume(total)
            if self._block_cut_text:
                self.blocked_once = True
                return b""
            return raw

        if msg_type == 150:  # EndOfContinuousUpdates: 1 byte
            return self._consume(1)

        if msg_type == 248:  # ServerFence: type(1)+pad(3)+flags(4)+len(1)+payload
            if len(buf) < 9:
                return None
            payload_len = buf[8]
            total = 9 + payload_len
            if len(buf) < total:
                return None
            return self._consume(total)

        if msg_type == 250:  # XVP: type(1)+pad(1)+ver(1)+op(1)
            if len(buf) < 4:
                return None
            return self._consume(4)

        raise RfbProtocolError(
            f"unrecognized server->client RFB message type {msg_type} while SetEncodings is "
            "restricted to Raw/CopyRect for this session"
        )

    def _take_rect(self) -> bytes | None:
        buf = self._buf
        if len(buf) < 12:  # x(2)+y(2)+w(2)+h(2)+encoding(4)
            return None
        width = int.from_bytes(buf[4:6], "big")
        height = int.from_bytes(buf[6:8], "big")
        encoding = int.from_bytes(buf[8:12], "big", signed=True)

        if encoding == 1:  # CopyRect: src-x(2)+src-y(2)
            total = 12 + 4
        elif encoding == 0:  # Raw: width*height*bytes-per-pixel
            if self._pixel_format.bytes_per_pixel is None:
                raise RfbProtocolError("Raw rectangle received before any client SetPixelFormat was observed")
            total = 12 + width * height * self._pixel_format.bytes_per_pixel
        else:
            raise RfbProtocolError(
                f"unexpected FramebufferUpdate rectangle encoding {encoding} — "
                "SetEncodings was restricted to Raw(0)/CopyRect(1) for this session, "
                "the sandbox VNC server did not honor it"
            )

        if len(buf) < total:
            return None
        raw = self._consume(total)
        self._fbu_rects_remaining -= 1
        return raw

    def _consume(self, n: int) -> bytes:
        raw = bytes(self._buf[:n])
        del self._buf[:n]
        return raw


def _build_set_encodings(encodings: tuple[int, ...]) -> bytes:
    out = bytearray()
    out.append(2)  # msg-type
    out.append(0)  # padding
    out += len(encodings).to_bytes(2, "big")
    for enc in encodings:
        out += int(enc).to_bytes(4, "big", signed=True)
    return bytes(out)
