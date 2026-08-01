"""Parsing and rendering of the Anthbot map archive.

The mower's map is a gzipped tar named ``map_manager_<sn>.tar.gz``, fetched
from the presigned-URL endpoint with sub_category=map. It holds:

* ``iot_map.bin``     — the mowable lawn as polygons
* ``iot_bridge.bin``  — connections between separate lawn areas
* ``area_setting.json`` — zones, no-go areas and ride-on paths

Both binaries share a header and store coordinates as little-endian int32
**millimetres**. See PROTOCOL.md for the byte layout and how it was verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import json
import struct
import tarfile
from typing import Any

MAP_MEMBER = "iot_map.bin"
BRIDGE_MEMBER = "iot_bridge.bin"
AREA_MEMBER = "area_setting.json"

# Guards against a corrupt length field sending us off the end of the buffer.
_MAX_POINTS_PER_RING = 100_000

Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class MowerMap:
    """Geometry extracted from the map archive, in millimetres."""

    lawn: list[list[Point]] = field(default_factory=list)
    bridges: list[list[Point]] = field(default_factory=list)
    area_definition: dict[str, Any] = field(default_factory=dict)
    map_id: int | None = None
    resolution_m: float | None = None
    origin_m: tuple[float, float] | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether there is nothing to draw."""
        return not self.lawn and not self.bridges


def _read_rings(raw: bytes, offset: int, *, id_prefixed: bool) -> list[list[Point]]:
    """Read ``[count][count * (int32 x, int32 y)]`` records until the buffer ends.

    ``iot_bridge.bin`` prefixes each record with a one-byte segment id.
    """
    rings: list[list[Point]] = []
    while offset + (5 if id_prefixed else 4) <= len(raw):
        if id_prefixed:
            offset += 1
        (count,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        if not 0 < count <= _MAX_POINTS_PER_RING:
            break
        if offset + count * 8 > len(raw):
            break
        rings.append(
            [struct.unpack_from("<ii", raw, offset + i * 8) for i in range(count)]
        )
        offset += count * 8
    return rings


def parse_map_binary(raw: bytes) -> tuple[list[list[Point]], dict[str, Any]]:
    """Parse ``iot_map.bin`` into polygons plus header metadata."""
    if len(raw) < 35:
        return [], {}
    header_size = raw[0]
    meta = {
        "map_id": struct.unpack_from("<Q", raw, 27)[0],
        "resolution_m": struct.unpack_from("<f", raw, 15)[0],
        "origin_m": struct.unpack_from("<ff", raw, 19),
    }
    return _read_rings(raw, header_size, id_prefixed=False), meta


def parse_bridge_binary(raw: bytes) -> list[list[Point]]:
    """Parse ``iot_bridge.bin`` into connecting line segments."""
    if len(raw) < 15:
        return []
    return _read_rings(raw, raw[0], id_prefixed=True)


def parse_archive(raw: bytes) -> MowerMap:
    """Unpack the map archive. Blocking — call from the executor."""
    map_bin = bridge_bin = b""
    area: dict[str, Any] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                handle = archive.extractfile(info)
                if handle is None:
                    continue
                name = info.name.rsplit("/", 1)[-1]
                if name == MAP_MEMBER:
                    map_bin = handle.read()
                elif name == BRIDGE_MEMBER:
                    bridge_bin = handle.read()
                elif name == AREA_MEMBER:
                    try:
                        parsed = json.loads(handle.read().decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        parsed = None
                    if isinstance(parsed, dict):
                        area = parsed
    except (tarfile.TarError, EOFError, OSError):
        return MowerMap()

    lawn, meta = parse_map_binary(map_bin) if map_bin else ([], {})
    return MowerMap(
        lawn=lawn,
        bridges=parse_bridge_binary(bridge_bin) if bridge_bin else [],
        area_definition=area,
        map_id=meta.get("map_id"),
        resolution_m=meta.get("resolution_m"),
        origin_m=meta.get("origin_m"),
    )


def _polygons(area: dict[str, Any], key: str) -> list[list[Point]]:
    """Return polygons from an area_setting.json list, skipping empty ones."""
    entries = area.get(key)
    if not isinstance(entries, list):
        return []
    result: list[list[Point]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        vertices = entry.get("vertexs")
        if not isinstance(vertices, list) or len(vertices) < 3:
            continue
        points = [
            (int(v[0]), int(v[1]))
            for v in vertices
            if isinstance(v, list) and len(v) >= 2
        ]
        if len(points) >= 3:
            result.append(points)
    return result


# Colours chosen to stay legible on both light and dark dashboards.
_BACKGROUND = "#1c2521"
_LAWN_FILL = "#4c8c4a"
_LAWN_EDGE = "#8fd18c"
_ZONE_EDGE = "#ffd54f"
_FORBID_FILL = "#e5737355"
_FORBID_EDGE = "#e57373"
_BRIDGE = "#64b5f6"


def render_svg(mower_map: MowerMap, *, width: int = 900, padding: int = 300) -> str:
    """Render the map as an SVG document.

    Device coordinates have y pointing up; SVG has it pointing down, so y is
    mirrored. Stroke widths are in millimetres because the viewBox is.
    """
    area = mower_map.area_definition
    zones = _polygons(area, "custom_areas")
    forbidden = _polygons(area, "forbid_areas") + _polygons(
        area, "remote_forbid_areas"
    )

    everything = [
        *(p for ring in mower_map.lawn for p in ring),
        *(p for seg in mower_map.bridges for p in seg),
        *(p for ring in zones for p in ring),
        *(p for ring in forbidden for p in ring),
    ]
    if not everything:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
            f'width="{width}"><rect width="100" height="100" '
            f'fill="{_BACKGROUND}"/></svg>'
        )

    xs = [p[0] for p in everything]
    ys = [p[1] for p in everything]
    min_x, max_x = min(xs) - padding, max(xs) + padding
    min_y, max_y = min(ys) - padding, max(ys) + padding
    box_w, box_h = max_x - min_x, max_y - min_y

    def place(point: Point) -> str:
        return f"{point[0] - min_x:.0f},{max_y - point[1]:.0f}"

    def ring(points: list[Point]) -> str:
        return " ".join(place(p) for p in points)

    height = max(1, round(width * box_h / box_w)) if box_w else width
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {box_w} {box_h}" width="{width}" height="{height}">',
        f'<rect width="{box_w}" height="{box_h}" fill="{_BACKGROUND}"/>',
    ]
    for points in mower_map.lawn:
        parts.append(
            f'<polygon points="{ring(points)}" fill="{_LAWN_FILL}" '
            f'stroke="{_LAWN_EDGE}" stroke-width="40"/>'
        )
    for points in mower_map.bridges:
        parts.append(
            f'<polyline points="{ring(points)}" fill="none" stroke="{_BRIDGE}" '
            'stroke-width="60" stroke-linecap="round"/>'
        )
    for points in forbidden:
        parts.append(
            f'<polygon points="{ring(points)}" fill="{_FORBID_FILL}" '
            f'stroke="{_FORBID_EDGE}" stroke-width="40"/>'
        )
    for points in zones:
        parts.append(
            f'<polygon points="{ring(points)}" fill="none" stroke="{_ZONE_EDGE}" '
            'stroke-width="45" stroke-dasharray="150,90"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
