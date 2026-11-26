"""ATX v1 track inspection. Never resolve a duplicate or invent a sector."""

from dataclasses import dataclass
from struct import unpack_from


@dataclass(frozen=True)
class Track:
    number: int
    # ID, controller status, track-relative data offset (0 = no data)
    headers: list[tuple[int, int, int]]
    block: memoryview
    data_end: int
    flags: int
    extensions: bool


def tracks(data: bytes) -> list[Track]:
    if len(data) < 48 or data[:4] != b"AT8X":
        raise ValueError("Truncated or invalid ATX header.")
    version, minimum = unpack_from("<HH", data, 4)
    if version != 1 or minimum > 1:
        raise ValueError(f"Unsupported ATX version {version} (minimum {minimum}).")
    pos, end = unpack_from("<II", data, 28)
    if end == 0:
        end = len(data)
    if not 48 <= pos < end <= len(data):
        raise ValueError("Invalid ATX track-data bounds.")
    result = []
    while pos < end:
        if pos + 32 > end:
            raise ValueError("Truncated ATX track header.")
        size, kind = unpack_from("<IH", data, pos)
        count = unpack_from("<H", data, pos + 10)[0]
        flags, header = unpack_from("<II", data, pos + 16)
        if kind or not 32 <= header <= size or pos + size > end:
            raise ValueError("Invalid ATX track record.")
        block = memoryview(data)[pos : pos + size]
        q = header
        headers = None
        data_span = None
        extensions = False
        while q + 8 <= size:
            length, tag = unpack_from("<IB", block, q)
            if not length:
                if q + 8 != size:
                    raise ValueError("Unexpected bytes after ATX track terminator.")
                break
            if length < 8 or q + length > size:
                raise ValueError("Invalid ATX track chunk length.")
            if tag == 1:
                if headers is not None or length != 8 + count * 8:
                    raise ValueError("Invalid ATX sector list.")
                headers = []
                for i in range(count):
                    sector, status, _, offset = unpack_from(
                        "<BBHI", block, q + 8 + i * 8
                    )
                    headers.append((sector, status, offset))
            elif tag == 0:
                if data_span is not None:
                    raise ValueError("Multiple ATX sector-data chunks not supported.")
                data_span = (q + 8, q + length)
            else:
                extensions = True  # weak/extended sectors, etc.
            q += length
        else:
            raise ValueError("Missing ATX track terminator.")
        if headers is None:
            raise ValueError("Missing ATX sector list.")
        for _, _, offset in headers:
            if offset and not (data_span and data_span[0] <= offset < data_span[1]):
                raise ValueError("ATX sector points outside its data chunk.")
        result.append(
            Track(
                block[8],
                headers,
                block,
                data_span[1] if data_span else 0,
                flags,
                extensions,
            )
        )
        pos += size
    return result


def description(records: list[Track]) -> str:
    errors = duplicates = total = 0
    seen = set()
    for track in records:
        for sector, status, _ in track.headers:
            key = (track.number, sector)
            duplicates += key in seen
            seen.add(key)
            errors += status != 0
            total += 1
    return f"ATX v1: {len(records)} tracks, {total} sector records, {duplicates} duplicate IDs, {errors} flagged records."


def sd_sector_window(data: bytes, first: int, last: int) -> bytes:
    """Sectors first..last of an allowlisted disk, from complete clean tracks only.

    Tracks outside the window (such as a protected boot track) are not read.
    """
    wanted = range((first - 1) // 18, (last - 1) // 18 + 1)
    sectors: dict[int, memoryview] = {}
    for track in tracks(data):
        if track.number not in wanted:
            continue
        if track.flags or track.extensions or len(track.headers) != 18:
            raise ValueError("Unexpected ATX geometry for this recipe.")
        for sector, status, offset in track.headers:
            key = track.number * 18 + sector
            if (
                status
                or not 1 <= sector <= 18
                or key in sectors
                or not offset
                or offset + 128 > track.data_end
            ):
                raise ValueError("Cannot map this ATX sector losslessly.")
            sectors[key] = track.block[offset : offset + 128]
    if len(sectors) != len(wanted) * 18:
        raise ValueError("Incomplete ATX disk.")
    return b"".join(sectors[i] for i in range(first, last + 1))


def linear_sd_disk(data: bytes, track_count: int) -> bytes:
    """Used only on allowlisted complete 18-sector single-density tracks."""
    sectors: dict[int, memoryview] = {}
    for track in tracks(data):
        if (
            track.flags
            or track.extensions
            or track.number >= track_count
            or len(track.headers) != 18
        ):
            raise ValueError("Unexpected ATX geometry for this recipe.")
        for sector, status, offset in track.headers:
            key = track.number * 18 + sector
            if (
                status
                or not 1 <= sector <= 18
                or key in sectors
                or not offset
                or offset + 128 > track.data_end
            ):
                raise ValueError("Cannot map this ATX sector losslessly.")
            sectors[key] = track.block[offset : offset + 128]
    if len(sectors) != track_count * 18:
        raise ValueError("Incomplete ATX disk.")
    return b"".join(sectors[i] for i in range(1, len(sectors) + 1))
