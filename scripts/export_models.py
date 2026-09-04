#!/usr/bin/env python3
"""Export every Saturn V component from saturnV.xml to a binary STL file.

Component UIDs are discovered by parsing the CPACS file with XPath rather than
through TiGL's UID manager, which keeps the script independent of changes to
TiGL's internal bindings. Geometry is then fetched per UID and written through
TiGL's STL exporter.

GLB would be the better web format, but the OCCT shipped with TiGL is built
without RapidJSON, so RWGltf_CafWriter is unavailable in this environment.

Duct cutouts are switched on explicitly: TiGL builds every component without
them by default, so the S-IC LOX suction line tunnels would be missing from the
RP-1 tank loft. The flag is set right after opening the configuration, because
lofts are cached on first build.

A failing component is skipped rather than fatal; the run only aborts if
nothing could be exported at all. Baffles (CPACS wallSegments) are open face
compounds rather than solids; STL and the viewer handle that fine, but a
baffle whose trimming collapses to nothing yields a zero-triangle file and is
reported as skipped.
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path
from lxml import etree

from tixi3.tixi3wrapper import Tixi3
from tigl3.tigl3wrapper import Tigl3
from tigl3 import configuration

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CPACS_FILE = REPO_ROOT / "saturnV.xml"
OUTPUT_DIR = REPO_ROOT / "web" / "public" / "models"
CONFIG_UID = "saturnV"

# Tessellation accuracy, passed on to BRepMesh_IncrementalMesh. TiGL's own
# default is 0.001, which yields roughly 1,070,000 triangles for a 110 m
# launcher. Larger values mean fewer triangles, smaller files and less VRAM.
DEFLECTION = float(os.environ.get("TIGL_DEFLECTION", "0.001"))

# Ducts are disabled by default in TiGL, independently of what CPACS defines.
# Without this flag the LOX suction line tunnels through s-ic_rp1 are not
# cut and the vessel is exported closed. Set TIGL_DUCT_CUTOUTS=0 to compare
# against the uncut geometry.
WITH_DUCT_CUTOUTS = os.environ.get("TIGL_DUCT_CUTOUTS", "1").lower() not in ("0", "false", "no")

# Per-category CPACS XPath plus the frontend defaults written to models.json.
# "opacity" seeds the initial position of the group transparency slider.
# Baffles are wallSegments below vessel/structure/walls. They are not part of
# the fuelTank loft (CCPACSFuelTank::BuildLoft only groups the vessel lofts,
# and a vessel loft is the OML), so they have to be exported as components in
# their own right. CCPACSWallSegment is a CTiglAbstractGeometricComponent and
# registers itself with the UID manager, so get_geometric_component works.
CATEGORIES: dict[str, dict] = {
    "fuselage": {"xpath": "//fuselages/fuselage", "opacity": 1.0, "color": None},
    "genericSystem": {"xpath": "//genericSystems/genericSystem", "opacity": 1.0, "color": None},
    "wing": {"xpath": "//wings/wing", "opacity": 1.0, "color": None},
    "enginePylon": {"xpath": "//enginePylons/enginePylon", "opacity": 1.0, "color": None},
    "fuelTank": {"xpath": "//fuelTanks/fuelTank", "opacity": 1.0, "color": "#3b6ea8"},
    "baffle": {
        "xpath": "//fuelTanks//walls/wallSegments/wallSegment",
        "opacity": 1.0,
        "color": "#e0913c",
    },
}


def discover_uids(cpacs_file: Path) -> list[dict]:
    tree = etree.parse(str(cpacs_file))
    components = []

    for category, cfg in CATEGORIES.items():
        for node in tree.xpath(cfg["xpath"]):
            uid = node.get("uID")
            if not uid:
                # wallSegment/@uID is optional in CPACS; without it TiGL cannot
                # register the component and it cannot be exported.
                print(f"  WARNING: <{node.tag}> without uID skipped ({category})")
                continue
            # Nearest enclosing fuelTank, used by the viewer so that a baffle
            # travels with its tank in the exploded view instead of drifting
            # out of it.
            tank = node.xpath("ancestor::fuelTank[1]")
            parent_uid = tank[0].get("uID") if tank else None

            components.append(
                {
                    "uid": uid,
                    "category": category,
                    "opacity": cfg["opacity"],
                    "color": cfg["color"],
                    "parent": parent_uid,
                }
            )

    return components


def convert_stl_to_binary(path: Path) -> tuple[int, int, int]:
    """Convert an ASCII STL file in place to binary STL.

    TiGL never resets the ASCII mode on OCCT's StlAPI_Writer and StlOptions has
    no switch for it, so the conversion has to happen afterwards. ASCII costs
    around 253 bytes per triangle against 50 for binary, and binary lets
    three.js' STLLoader build Float32Array slices directly instead of parsing
    millions of numbers out of strings.

    Deliberately implemented without numpy: the python-internal pixi
    environment only guarantees lxml and pythonocc-core.

    :return: (triangles, bytes before, bytes after)
    """
    size_before = path.stat().st_size

    # A binary STL is always exactly 84 + 50 * triangles bytes. The header text
    # is no criterion, as binary files often start with "solid" as well.
    if size_before >= 84:
        with path.open("rb") as fh:
            fh.seek(80)
            n_binary = struct.unpack("<I", fh.read(4))[0]
        if size_before == 84 + 50 * n_binary:
            return n_binary, size_before, size_before

    normal: tuple[float, ...] | None = None
    vertices: list[tuple[float, ...]] = []
    body = bytearray()
    count = 0

    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("facet normal"):
                normal = tuple(float(x) for x in stripped.split()[2:5])
                vertices = []
            elif stripped.startswith("vertex"):
                vertices.append(tuple(float(x) for x in stripped.split()[1:4]))
            elif stripped.startswith("endfacet"):
                if normal is None or len(vertices) != 3:
                    raise RuntimeError(f"Incomplete facet in {path.name}")
                body += struct.pack(
                    "<12fH", *normal, *vertices[0], *vertices[1], *vertices[2], 0
                )
                count += 1

    if count == 0:
        raise RuntimeError(f"No triangles found in {path.name}")

    with path.open("wb") as fh:
        fh.write(b"TiGL binary STL".ljust(80, b"\0"))
        fh.write(struct.pack("<I", count))
        fh.write(body)

    return count, size_before, path.stat().st_size


def export_stl(loft, out_file: Path) -> None:
    """Write a TiGL loft to STL. The file is still ASCII afterwards."""
    from tigl3.exports import TriangulatedExportOptions, create_exporter

    out_file.parent.mkdir(parents=True, exist_ok=True)
    exporter = create_exporter("stl")
    exporter.add_shape(loft, TriangulatedExportOptions(DEFLECTION))
    ok = exporter.write(str(out_file))
    if ok is False:
        raise RuntimeError(f"STL export failed for {out_file}")
    if not out_file.is_file() or out_file.stat().st_size == 0:
        raise RuntimeError(f"STL file empty or missing: {out_file}")


def main() -> None:
    components = discover_uids(CPACS_FILE)
    print(
        f"Found {len(components)} components, deflection {DEFLECTION}, "
        f"duct cutouts {'on' if WITH_DUCT_CUTOUTS else 'off'}"
    )
    for c in components:
        print(f"  [{c['category']}] {c['uid']}")

    tixi = Tixi3()
    tixi.open(str(CPACS_FILE))
    tigl = Tigl3()
    tigl.open(tixi, CONFIG_UID)
    tigl.configurationSetWithDuctCutouts(WITH_DUCT_CUTOUTS)

    mgr = configuration.CCPACSConfigurationManager.get_instance()
    config = mgr.get_configuration(tigl._handle.value)
    uid_mgr = config.get_uidmanager()

    manifest = []
    failed = []
    total_tris = 0
    total_ascii = 0
    total_binary = 0

    for component in components:
        uid = component["uid"]
        try:
            comp = uid_mgr.get_geometric_component(uid)
            loft = comp.get_loft()
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIPPED (geometry) {uid}: {exc}")
            failed.append((uid, f"geometry: {exc}"))
            continue

        filename = f"{uid}.stl"
        out_path = OUTPUT_DIR / filename
        try:
            export_stl(loft, out_path)
            tris, before, after = convert_stl_to_binary(out_path)
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIPPED (STL export) {uid}: {exc}")
            failed.append((uid, f"STL export: {exc}"))
            continue

        total_tris += tris
        total_ascii += before
        total_binary += after
        print(
            f"  exported {filename} "
            f"({tris:,} triangles, {before / 1e6:.1f} MB ASCII -> {after / 1e6:.1f} MB binary)"
        )

        manifest.append(
            {
                "uid": uid,
                "category": component["category"],
                "file": filename,
                "opacity": component["opacity"],
                "color": component["color"],
                "parent": component["parent"],
            }
        )

    tigl.close()
    tixi.close()

    manifest_path = OUTPUT_DIR / "models.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"Exported {len(manifest)} / {len(components)} components")
    print(f"Triangles: {total_tris:,} (deflection {DEFLECTION})")
    if total_binary:
        print(
            f"Size: {total_ascii / 1e6:.1f} MB ASCII -> {total_binary / 1e6:.1f} MB binary "
            f"(factor {total_ascii / total_binary:.1f})"
        )
    if failed:
        print(f"Failed: {len(failed)}")
        for uid, reason in failed:
            print(f"  - {uid}: {reason}")
    print(f"models.json: {manifest_path}")
    sys.stdout.flush()

    if not manifest:
        raise SystemExit("Not a single component could be exported.")


if __name__ == "__main__":
    main()
