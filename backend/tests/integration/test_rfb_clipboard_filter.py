"""app/core/rfb_clipboard_filter.py — pure protocol-framing logic, no DB or
Session Agent involved despite living alongside the other integration
tests (this suite's tests/conftest.py fixtures aren't needed here, but
collection still goes through it like every other test module in this
directory — see its own docstring for how to actually run this suite).

Covers: ClientCutText/ServerCutText blocked per ClipboardMode, SetEncodings
rewritten to Raw/CopyRect only when the server direction is restricted,
messages split across multiple feed() calls (the WebSocket/TCP relay never
guarantees one RFB message per read), the BIDIRECTIONAL_TEXT no-op fast
path staying a pure passthrough, and fail-closed behavior on an
unrecognized message type.
"""

from app.core.rfb_clipboard_filter import RfbProtocolError, build_filters
from app.models.enums import ClipboardMode


def _set_pixel_format(bpp: int = 32) -> bytes:
    return bytes([0, 0, 0, 0, bpp, 24, 0, 1, 0, 255, 0, 255, 0, 255, 0, 8, 16, 0, 0, 0])


def _set_encodings(*encodings: int) -> bytes:
    out = bytearray([2, 0]) + len(encodings).to_bytes(2, "big")
    for enc in encodings:
        out += int(enc).to_bytes(4, "big", signed=True)
    return bytes(out)


def _client_cut_text(text: bytes) -> bytes:
    return bytes([6, 0, 0, 0]) + len(text).to_bytes(4, "big", signed=True) + text


def _server_cut_text(text: bytes) -> bytes:
    return bytes([3, 0, 0, 0]) + len(text).to_bytes(4, "big", signed=True) + text


def _fbu_raw_rect(width: int, height: int, bpp: int) -> bytes:
    header = bytes([0, 0]) + (1).to_bytes(2, "big")  # type, pad, num_rects=1
    rect_header = (
        (0).to_bytes(2, "big")
        + (0).to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + height.to_bytes(2, "big")
        + (0).to_bytes(4, "big", signed=True)
    )
    pixels = bytes(width * height * bpp)
    return header + rect_header + pixels


def test_bidirectional_text_is_pure_passthrough_no_parsing():
    client, server = build_filters(ClipboardMode.BIDIRECTIONAL_TEXT)
    garbage = b"\xff\x00not-valid-rfb-but-must-pass-through-unchanged"
    assert client.feed(garbage) == garbage
    assert server.feed(garbage) == garbage
    assert not client.blocked_once
    assert not server.blocked_once


def test_none_mode_blocks_client_cut_text_and_rewrites_set_encodings():
    client, _server = build_filters(ClipboardMode.NONE)

    out = client.feed(_set_pixel_format())
    assert out == _set_pixel_format()

    out = client.feed(_set_encodings(7, 5, 0))  # Tight, Hextile, Raw requested
    assert out == _set_encodings(1, 0)  # forced down to CopyRect, Raw

    out = client.feed(_client_cut_text(b"secret"))
    assert out == b""
    assert client.blocked_once


def test_none_mode_blocks_server_cut_text_and_forwards_raw_framebuffer_update():
    client, server = build_filters(ClipboardMode.NONE)
    client.feed(_set_pixel_format(bpp=32))  # shares pixel-format state with `server`

    fbu = _fbu_raw_rect(width=2, height=2, bpp=4)
    assert server.feed(fbu) == fbu

    out = server.feed(_server_cut_text(b"leaked?"))
    assert out == b""
    assert server.blocked_once


def test_local_to_remote_allows_client_blocks_server():
    client, server = build_filters(ClipboardMode.LOCAL_TO_REMOTE)
    client.feed(_set_pixel_format())

    assert client.feed(_client_cut_text(b"paste me in")) == _client_cut_text(b"paste me in")
    assert not client.blocked_once

    assert server.feed(_server_cut_text(b"nope")) == b""
    assert server.blocked_once


def test_remote_to_local_allows_server_blocks_client():
    client, server = build_filters(ClipboardMode.REMOTE_TO_LOCAL)

    assert client.feed(_client_cut_text(b"nope")) == b""
    assert client.blocked_once

    # No restriction needed for this direction -> pure passthrough, any
    # encoding is fine since SetEncodings was never rewritten.
    assert server.feed(_server_cut_text(b"welcome through")) == _server_cut_text(b"welcome through")
    assert not server.blocked_once


def test_message_split_across_multiple_feed_calls_is_still_recognized():
    client, _ = build_filters(ClipboardMode.NONE)
    cct = _client_cut_text(b"fragmented-secret")
    midpoint = 5
    assert client.feed(cct[:midpoint]) == b""
    assert client.feed(cct[midpoint:]) == b""
    assert client.blocked_once


def test_unrecognized_client_message_type_fails_closed():
    client, _ = build_filters(ClipboardMode.NONE)
    try:
        client.feed(bytes([199, 0, 0, 0, 0, 0, 0, 0]))
    except RfbProtocolError:
        pass
    else:
        raise AssertionError("expected RfbProtocolError for an unrecognized message type")


def test_unexpected_rectangle_encoding_fails_closed_when_restricted():
    client, server = build_filters(ClipboardMode.NONE)
    client.feed(_set_pixel_format())

    header = bytes([0, 0]) + (1).to_bytes(2, "big")
    # encoding 7 == Tight — never offered once SetEncodings was forced to
    # Raw/CopyRect, so a server sending it anyway must fail closed rather
    # than have this module guess its (compressed, unknowable-without-
    # decoding) length.
    rect_header = (
        (0).to_bytes(2, "big")
        + (0).to_bytes(2, "big")
        + (2).to_bytes(2, "big")
        + (2).to_bytes(2, "big")
        + (7).to_bytes(4, "big", signed=True)
    )
    try:
        server.feed(header + rect_header)
    except RfbProtocolError:
        pass
    else:
        raise AssertionError("expected RfbProtocolError for an unexpected rectangle encoding")
