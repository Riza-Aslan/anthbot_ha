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

import base64
import binascii
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


# curpath is a 22-byte header followed by 6-byte records: int16 x, int16 y and
# a 2-byte field that has been constant in every sample. Its coordinates are
# centimetres while the map is millimetres — established by transforming the
# path both ways and checking which lands inside the lawn polygons.
_CURPATH_HEADER = 22
_CURPATH_RECORD = 6
CURPATH_TO_MM = 10
# pose2d is metres.
POSE_TO_MM = 1000


def parse_curpath(value: str | None) -> list[Point]:
    """Decode the shadow's base64 ``curpath`` into map millimetres."""
    if not isinstance(value, str) or not value:
        return []
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return []
    if len(raw) <= _CURPATH_HEADER:
        return []
    body = raw[_CURPATH_HEADER:]
    points: list[Point] = []
    for offset in range(0, len(body) - _CURPATH_RECORD + 1, _CURPATH_RECORD):
        x, y = struct.unpack_from("<hh", body, offset)
        points.append((x * CURPATH_TO_MM, y * CURPATH_TO_MM))
    return points


def parse_position(state: dict[str, Any]) -> Point | None:
    """Return the mower's position in map millimetres, if it reports one."""
    pose = state.get("anti_loss_pose")
    if not isinstance(pose, dict):
        return None
    pose2d = pose.get("pose2d")
    if not isinstance(pose2d, dict):
        return None
    x, y = pose2d.get("x"), pose2d.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return (round(x * POSE_TO_MM), round(y * POSE_TO_MM))


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


# Palette sampled from the Anthbot app so the map looks familiar next to it.
# Carried in a <style> block rather than per-element attributes so the dark
# variant can be a media query — which browsers honour even for an SVG loaded
# through <img>, as Home Assistant does.
_STYLE = """<style>
  .bg     { fill: #ecedf4 }
  .lawn   { fill: #9da4fc; stroke: #858cf5; stroke-width: 30; stroke-linejoin: round }
  .zone   { fill: #f0afb8; fill-opacity: .45; stroke: #e2808d; stroke-width: 35;
            stroke-dasharray: 170 100; stroke-linecap: round }
  .forbid { fill: #ff8a8a; fill-opacity: .35; stroke: #e05c5c; stroke-width: 35 }
  .bridge { fill: none; stroke: #b9bdcb; stroke-width: 70; stroke-linecap: round;
            stroke-dasharray: 30 120 }
  .track  { fill: none; stroke: #ffffff; stroke-opacity: .75; stroke-width: 60;
            stroke-linecap: round; stroke-linejoin: round }
  .mower  { fill: #ffffff; stroke: #2a2f7d; stroke-width: 55 }
  .mowerd { fill: #2a2f7d }
  @media (prefers-color-scheme: dark) {
    .bg     { fill: #191b2a }
    .lawn   { fill: #6f76d8; stroke: #8f96ee }
    .bridge { stroke: #5b6070 }
    .mower  { fill: #ffffff; stroke: #12142b }
    .mowerd { fill: #12142b }
  }
</style>"""


def render_svg(
    mower_map: MowerMap,
    *,
    path: list[Point] | None = None,
    position: Point | None = None,
    width: int = 900,
    padding: int = 300,
    max_aspect: float = 1.6,
) -> str:
    """Render the map as an SVG document.

    Device coordinates have y pointing up; SVG has it pointing down, so y is
    mirrored. Stroke widths are in millimetres because the viewBox is.

    A long, narrow garden would otherwise produce an extremely tall image that
    dominates a dashboard — a 3.4 x 10.9 m lawn is a 1:2.8 strip, over 1900 px
    tall in a full-width card. ``max_aspect`` bounds the ratio in either
    direction by widening the short side of the view box, which pads the
    drawing with background instead of distorting it.
    """
    area = mower_map.area_definition
    zones = _polygons(area, "custom_areas")
    forbidden = _polygons(area, "forbid_areas") + _polygons(
        area, "remote_forbid_areas"
    )

    # The mower and its track are included in the extent so it stays visible
    # even when it drives outside the mapped lawn.
    everything = [
        *(p for ring in mower_map.lawn for p in ring),
        *(p for seg in mower_map.bridges for p in seg),
        *(p for ring in zones for p in ring),
        *(p for ring in forbidden for p in ring),
        *(path or []),
        *([position] if position else []),
    ]
    if not everything:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
            f'width="{width}">{_STYLE}'
            '<rect class="bg" width="100" height="100"/></svg>'
        )

    xs = [p[0] for p in everything]
    ys = [p[1] for p in everything]
    min_x, max_x = min(xs) - padding, max(xs) + padding
    min_y, max_y = min(ys) - padding, max(ys) + padding
    box_w, box_h = max_x - min_x, max_y - min_y

    if max_aspect > 0 and box_w > 0 and box_h > 0:
        if box_h / box_w > max_aspect:
            grow = (box_h / max_aspect - box_w) / 2
            min_x, max_x = min_x - grow, max_x + grow
        elif box_w / box_h > max_aspect:
            grow = (box_w / max_aspect - box_h) / 2
            min_y, max_y = min_y - grow, max_y + grow
        box_w, box_h = max_x - min_x, max_y - min_y

    def place(point: Point) -> str:
        return f"{point[0] - min_x:.0f},{max_y - point[1]:.0f}"

    def ring(points: list[Point]) -> str:
        return " ".join(place(p) for p in points)

    height = max(1, round(width * box_h / box_w)) if box_w else width
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {box_w} {box_h}" width="{width}" height="{height}">',
        _STYLE,
        f'<rect class="bg" width="{box_w}" height="{box_h}"/>',
    ]
    for points in mower_map.lawn:
        parts.append(f'<polygon class="lawn" points="{ring(points)}"/>')
    for points in mower_map.bridges:
        parts.append(f'<polyline class="bridge" points="{ring(points)}"/>')
    for points in forbidden:
        parts.append(f'<polygon class="forbid" points="{ring(points)}"/>')
    for points in zones:
        parts.append(f'<polygon class="zone" points="{ring(points)}"/>')
    if path and len(path) >= 2:
        parts.append(f'<polyline class="track" points="{ring(path)}"/>')
    if position:
        cx, cy = position[0] - min_x, max_y - position[1]
        # Rounded square with a dot, echoing the app's mower marker.
        parts.append(
            f'<rect class="mower" x="{cx - 190:.0f}" y="{cy - 190:.0f}" '
            'width="380" height="380" rx="130"/>'
            f'<circle class="mowerd" cx="{cx:.0f}" cy="{cy:.0f}" r="80"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
