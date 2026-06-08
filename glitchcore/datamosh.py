"""Real datamoshing: strip I-frames from an mpeg4 AVI so P-frame motion
vectors bloom over the wrong content. Operates on the raw RIFF/AVI bytes.

This is best-effort. If parsing looks wrong it returns False and the caller
falls back to the un-moshed video.

AVI 'movi' list layout:  'LIST'(4) listSize(4) 'movi'(4) <chunks...>
Each chunk:              fourCC(4) size(4) data(size) [pad to even]
"""
from __future__ import annotations
import struct
import logging

log = logging.getLogger(__name__)
VOP_START = b"\x00\x00\x01\xb6"


def _is_iframe(data: bytes) -> bool:
    """An mpeg4 video chunk is an I-VOP if the 2 bits after the VOP start
    code (vop_coding_type) are 00."""
    i = data.find(VOP_START)
    if i < 0 or i + 4 >= len(data):
        return False
    return (data[i + 4] >> 6) & 0b11 == 0


def datamosh(in_avi: str, out_avi: str, keep_first: bool = True) -> bool:
    try:
        with open(in_avi, "rb") as f:
            buf = f.read()
        if buf[:4] != b"RIFF" or buf[8:12] != b"AVI ":
            return False

        m = buf.find(b"movi")               # offset of the 'movi' listType
        if m < 4:
            return False
        list_size = struct.unpack("<I", buf[m - 4:m])[0]   # size after the size field
        movi_start = m + 4                  # first chunk
        movi_end = min(len(buf), m + list_size)  # listType+data spans list_size bytes

        out_chunks = bytearray()
        p = movi_start
        seen_iframe = False
        kept = dropped = 0
        while p + 8 <= movi_end:
            cid = buf[p:p + 4]
            csize = struct.unpack("<I", buf[p + 4:p + 8])[0]
            advance = 8 + csize + (csize & 1)            # word-aligned
            payload = buf[p + 8:p + 8 + csize]
            is_video = cid[2:4] in (b"dc", b"db")
            if is_video and _is_iframe(payload):
                if keep_first and not seen_iframe:
                    seen_iframe = True
                    out_chunks += buf[p:p + advance]
                    kept += 1
                else:
                    dropped += 1                          # drop I-frame -> bloom
            else:
                out_chunks += buf[p:p + advance]
                kept += 1
            p += advance

        if dropped == 0:
            return False

        head = buf[:m - 8]                                # up to (not incl) 'LIST'
        new_payload = b"movi" + bytes(out_chunks)         # listType + chunks
        new_list = b"LIST" + struct.pack("<I", len(new_payload)) + new_payload
        new_file = bytearray(head) + new_list             # idx1 intentionally dropped
        new_file[4:8] = struct.pack("<I", len(new_file) - 8)  # fix RIFF size

        with open(out_avi, "wb") as f:
            f.write(new_file)
        log.info("datamosh: kept %d chunks, dropped %d I-frames", kept, dropped)
        return True
    except Exception as e:  # pragma: no cover
        log.warning("datamosh failed: %s", e)
        return False
