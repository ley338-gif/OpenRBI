"""ClamAV FileScanner implementation (docs/adr/0003, 0008): speaks clamd's
native protocol directly over TCP (INSTREAM/PING/VERSION) rather than
pulling in a third-party clamd client library, so timeout and error
handling are fully under our control for the fail-closed rules that
matter here — every failure mode raises ClamAVError, and callers must
treat that as "not clean," never as an implicit pass.
"""

import asyncio
import struct
from dataclasses import dataclass

from app.config import get_settings

_CHUNK_SIZE = 8192
_CONNECT_TIMEOUT = 5.0
_COMMAND_TIMEOUT = 5.0
_SCAN_TIMEOUT = 30.0


class ClamAVError(RuntimeError):
    pass


@dataclass
class ScanResult:
    infected: bool
    signature: str | None


async def _connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    settings = get_settings()
    try:
        return await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port), timeout=_CONNECT_TIMEOUT
        )
    except (OSError, TimeoutError) as exc:
        raise ClamAVError(f"cannot connect to clamd: {exc}") from exc


async def ping() -> bool:
    """Used for health reporting (Phase 19) — never raises, degrades to
    False on any error.
    """
    try:
        reader, writer = await _connect()
        writer.write(b"zPING\0")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(100), timeout=_COMMAND_TIMEOUT)
        writer.close()
        return response.rstrip(b"\0") == b"PONG"
    except (ClamAVError, OSError, TimeoutError):
        return False


async def signature_version() -> str | None:
    try:
        reader, writer = await _connect()
        writer.write(b"zVERSION\0")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(1000), timeout=_COMMAND_TIMEOUT)
        writer.close()
        return response.rstrip(b"\0").decode("utf-8", errors="replace") or None
    except (ClamAVError, OSError, TimeoutError):
        return None


async def scan(data: bytes) -> ScanResult:
    """Streams `data` to clamd via INSTREAM. Raises ClamAVError on any
    connection/protocol failure — callers (app/services/scanning.py) must
    treat that as fail-closed (docs/adr/0008: scanner unavailable means no
    automatic release), not as an implicit clean result.
    """
    reader, writer = await _connect()
    try:
        writer.write(b"zINSTREAM\0")
        for i in range(0, len(data), _CHUNK_SIZE):
            chunk = data[i : i + _CHUNK_SIZE]
            writer.write(struct.pack("!L", len(chunk)) + chunk)
        writer.write(struct.pack("!L", 0))
        await writer.drain()
        response = await asyncio.wait_for(reader.read(4096), timeout=_SCAN_TIMEOUT)
    except (OSError, TimeoutError) as exc:
        raise ClamAVError(f"scan failed: {exc}") from exc
    finally:
        writer.close()

    text = response.rstrip(b"\0").decode("utf-8", errors="replace").strip()
    # e.g. "stream: OK" or "stream: Eicar-Signature FOUND"
    if text.endswith("OK"):
        return ScanResult(infected=False, signature=None)
    if "FOUND" in text:
        signature = text.split(":", 1)[1].strip()
        signature = signature[: -len(" FOUND")] if signature.endswith(" FOUND") else signature
        return ScanResult(infected=True, signature=signature)
    raise ClamAVError(f"unexpected clamd response: {text!r}")
