#!/usr/bin/env python3
"""Render presentation figures of the Saturn V CPACS model in Blender.

The script consumes the per-component STL files and the ``models.json``
manifest written by ``scripts/export_models.py``. Materials are derived from
the CPACS category recorded in the manifest, so the colour coding of every
image follows the data model rather than a manual assignment.

Export the geometry at a finer tessellation than the web viewer uses before
rendering; the viewer default shows facets on the domes in close-ups::

    TIGL_DEFLECTION=0.0002 pixi run -e python-internal python scripts/export_models.py

Usage (headless)::

    blender --background --python scripts/render_saturnv.py
    blender --background --python scripts/render_saturnv.py -- --shots les,vessels
    blender --background --python scripts/render_saturnv.py -- --list
    blender --background --python scripts/render_saturnv.py -- --engine CYCLES --samples 256

Opening it interactively is often more useful while framing a new shot::

    blender --python scripts/render_saturnv.py -- --shots overview --no-render

Output is written to ``figures/render/<shot>.png`` with a transparent
background.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------
# Paths. SCRIPT_DIR assumes this file lives in <repo>/scripts/.
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MODEL_DIR = REPO_ROOT / "web" / "public" / "models"
MANIFEST = MODEL_DIR / "models.json"
OUTPUT_DIR = REPO_ROOT / "figures" / "render"

# --------------------------------------------------------------------------
# Palette. Identical to the DLR theme colours used in the slide deck, so that
# a component keeps one colour across every figure and the slides themselves.
# --------------------------------------------------------------------------

DLR_BLUE = "00658B"
DLR_TEAL = "0094A8"
DLR_LIGHT = "5F98CB"
DLR_YELLOW = "F8DE53"
STRUCTURE = "C8CCCE"

CATEGORY_STYLE: dict[str, dict] = {
    "fuselage": {"color": STRUCTURE, "roughness": 0.42, "metallic": 0.25},
    "wing": {"color": DLR_LIGHT, "roughness": 0.40, "metallic": 0.15},
    "enginePylon": {"color": DLR_LIGHT, "roughness": 0.40, "metallic": 0.15},
    "fuelTank": {"color": DLR_TEAL, "roughness": 0.42, "metallic": 0.05},
    "baffle": {"color": DLR_YELLOW, "roughness": 0.55, "metallic": 0.00},
    "genericSystem": {"color": DLR_BLUE, "roughness": 0.45, "metallic": 0.15},
}
FALLBACK_STYLE = {"color": STRUCTURE, "roughness": 0.45, "metallic": 0.20}

# Per-uID overrides. The LES close-up is the one figure where the colouring
# deliberately breaks the semantic rule: there it has to show the composition
# from primitives, not the element category.
UID_STYLE: dict[str, dict] = {
    # "apolloLES": {"color": DLR_TEAL},
}


# --------------------------------------------------------------------------
# Shot definitions
# --------------------------------------------------------------------------


@dataclass
class Shot:
    """One rendered image.

    :param include: uID or category names to show. Empty means everything.
    :param exclude: uID or category names to hide, applied after ``include``.
    :param ghost: uID or category names rendered near-transparent.
    :param direction: camera direction in Blender world space, pointing from
        the subject towards the camera. It is normalised on use.
    :param up_axis: which model axis is turned upwards. ``auto`` picks the
        longest bounding-box edge, which is the vehicle axis.
    :param ortho: orthographic projection. Mandatory whenever the image
        compares proportions, otherwise perspective distorts the comparison.
    :param section: cut the model with a half space and cap the cut faces.
        The normal is given in world space after the up-axis correction.
    :param orientation: "vertical" stands the vehicle up, "horizontal" lays it
        along the frame. A 110 m launcher standing upright in a landscape frame
        fills a narrow strip and nothing else, so whole-vehicle shots want the
        horizontal variant.
    :param tilt: degrees the nose is lifted out of the horizontal, applied
        after the vehicle has been laid down. Zero leaves the axis lying flat,
        which the standard camera direction renders nose-down — it reads as a
        launcher falling towards the ground. Around 22 puts the nose visibly
        up and to the right. Ignored for vertical shots.
    :param ghost_alpha: opacity of the components listed in ghost. Around 0.12
        for an outer shell that should almost disappear, 0.25 and above when
        the ghosted body itself still has to read as a volume. Values stack:
        a shot that ghosts five nested bodies needs half of what a single
        shell needs, because the eye sees every layer at once.
    :param ghost_flat: render the ghosted components without specular
        highlights. Worth setting whenever several ghosted bodies overlap the
        subject, see make_material.
    :param key_size: diameter of the key light relative to the model radius.
        Small values give hard shadows that model filigree structure; large
        values wash it out. Around 0.8 for single components, 1.6 and above
        for whole-vehicle views where hard shadows only add noise.
    """

    name: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    ghost: tuple[str, ...] = ()
    direction: tuple[float, float, float] = (0.72, -1.0, 0.34)
    up_axis: str = "auto"
    ortho: bool = False
    lens: float = 85.0
    margin: float = 1.04
    section: tuple[float, float, float] | None = None
    resolution: tuple[int, int] = (3400, 2400)
    freestyle: bool = True
    key_size: float = 0.8
    ghost_alpha: float = 0.12
    ghost_flat: bool = False
    orientation: str = "vertical"
    tilt: float = 0.0
    # Per-shot material overrides, keyed by category or uID and merged over
    # CATEGORY_STYLE/UID_STYLE. Needed where one figure wants a different
    # finish than the rest of the series: raising roughness widens the
    # specular lobe, which turns the disk-shaped highlight on a dome into a
    # broad sheen instead of a bright ring.
    style_overrides: dict = field(default_factory=dict)
    notes: str = ""


# Lage der Bilder für die Titel- und Abschnittsfolien. Sie teilen sich Neigung
# und Blickrichtung, damit die Folien als Serie zusammengehören.
SLIDE_TILT = 22.0
SLIDE_DIRECTION = (0.85, -1.0, 0.30)

SHOTS: list[Shot] = [
    # ---------------------------------------------------------- Gesamtansichten
    Shot(
        name="overview",
        direction=(0.85, -1.0, 0.30),
        resolution=(5000, 2800),
        key_size=1.8,
        orientation="horizontal",
        notes="Gesamtansicht für Titel- und Kapitelfolien.",
    ),
    Shot(
        name="overview_ghost",
        ghost=("fuselage", "wing", "enginePylon"),
        direction=(0.85, -1.0, 0.30),
        resolution=(5000, 2800),
        key_size=1.8,
        orientation="horizontal",
        notes="Struktur durchscheinend, Tanks und Systeme deckend. Folie 3.",
    ),
    Shot(
        name="overview_banner",
        ghost=("fuselage", "wing", "enginePylon"),
        direction=(0.30, -1.0, 0.10),
        resolution=(5000, 1500),
        key_size=1.8,
        orientation="horizontal",
        notes="Flacher Streifen, füllt das Format ohne Beschnitt.",
    ),
    Shot(
        name="overview_explicit",
        exclude=("fuelTank", "baffle", "genericSystem"),
        direction=(0.85, -1.0, 0.30),
        resolution=(5000, 2800),
        key_size=1.8,
        orientation="horizontal",
        notes="Nur die expliziten Aussengeometrien: fuselage, wing, "
              "enginePylon. Folie 7.",
    ),

    # ----------------------------------------------------------------- Tanks
    Shot(
        name="section_s_ic",
        include=("s-ic_thrustStructure", "s-ic_intertankSection",
                 "s-ic_forwardSkirt", "s-ic_rp1", "s-ic_lox",
                 "baffle"),
        section=(0.0, -1.0, 0.0),
        direction=(0.35, -1.0, 0.22),
        resolution=(4200, 3000),
        notes="Halbschnitt S-IC mit Domes und Schwallwänden. Folie 12.",
    ),
    Shot(
        name="vessels_ortho",
        include=("fuelTank", "baffle"),
        direction=(0.0, -1.0, 0.0),
        ortho=True,
        resolution=(4800, 2000),
        orientation="horizontal",
        notes="Seitenriss aller Vessels, orthografisch für den Proportions"
              "vergleich.",
    ),
    Shot(
        name="tanks_only",
        include=("fuelTank", "baffle"),
        direction=(0.85, -1.0, 0.30),
        resolution=(5000, 2800),
        key_size=1.8,
        orientation="horizontal",
        notes="Alle sechs Tanks freigestellt, ohne Struktur.",
    ),
    Shot(
        name="tanks_ghost",
        include=("fuelTank", "baffle"),
        # Every tank translucent, so the shells inside shells become visible:
        # S-II LOX sitting against the LH2 dome, S-IVB LOX inside the assembly.
        ghost=("fuelTank",),
        ghost_alpha=0.22,
        direction=(0.85, -1.0, 0.30),
        resolution=(5000, 2800),
        key_size=1.8,
        orientation="horizontal",
        notes="Alle Tanks durchscheinend -- zeigt die Verschachtelung der "
              "Vessels und die gemeinsame Bulkhead.",
    ),
    Shot(
        name="tanks_ghost_ortho",
        include=("fuelTank", "baffle"),
        ghost=("fuelTank",),
        ghost_alpha=0.22,
        direction=(0.0, -1.0, 0.0),
        ortho=True,
        resolution=(4800, 2000),
        orientation="horizontal",
        notes="Seitenriss der durchscheinenden Tanks, orthografisch.",
    ),
    Shot(
        name="baffles",
        # Naming the category would drag in the two RP-1 baffles as well,
        # whose tank is not part of this shot -- they would float in mid-air.
        include=("s-ic_lox",
                 "s-ic_lox_vessel_baffle1", "s-ic_lox_vessel_baffle2",
                 "s-ic_lox_vessel_baffle3", "s-ic_lox_vessel_baffle4"),
        ghost=("s-ic_lox",),
        direction=(0.55, -1.0, 0.30),
        resolution=(2600, 3200),
        key_size=0.5,
        notes="Schwallwände im S-IC-LOX-Tank, Hülle durchscheinend.",
    ),

    # --------------------------------------------------------------- Systems
    Shot(
        name="les",
        include=("apolloLES",),
        direction=(0.55, -1.0, 0.25),
        resolution=(1500, 3400),
        key_size=0.35,
        notes="Launch Escape System freigestellt. Folie 14.",
    ),
    Shot(
        name="feed_system",
        include=("s-ic_fuelFeed", "s-ic_loxFeed", "engines"),
        direction=(0.60, -1.0, 0.35),
        resolution=(4000, 3000),
        key_size=0.6,
        notes="Zuführung und Triebwerkscluster ohne Struktur. Folie 16.",
    ),
    Shot(
        name="feed_in_context",
        include=("s-ic_thrustStructure", "s-ic_rp1", "s-ic_lox",
                 "s-ic_fuelFeed", "s-ic_loxFeed", "engines",
                 "s-ic_engineShroud_f1_1", "s-ic_engineShroud_f1_2",
                 "s-ic_engineShroud_f1_3", "s-ic_engineShroud_f1_4"),
        ghost=("s-ic_thrustStructure", "enginePylon"),
        direction=(0.60, -1.0, 0.30),
        resolution=(4000, 3000),
        key_size=0.8,
        notes="Zuführung im Einbauraum, Struktur durchscheinend.",
    ),
    Shot(
        name="engines",
        include=("engines",),
        direction=(0.55, -1.0, 0.35),
        resolution=(3000, 2600),
        key_size=0.5,
        notes="F-1-Cluster: eine Definition, fünf Instanzen. Folie 15.",
    ),

    # ------------------------------------------- explizite Elementtypen, Folie 7
    Shot(
        name="fins",
        include=("s-ic_fin_a",),
        direction=(0.60, -1.0, 0.30),
        resolution=(3000, 2400),
        key_size=0.5,
        notes="Eine Finne als wing statt als fuselage. Vier zusammen lesen "
              "sich an ihren Einbaupositionen als Fragmente.",
    ),
    Shot(
        name="shrouds",
        include=("s-ic_engineShroud_f1_1",),
        direction=(0.60, -1.0, 0.30),
        resolution=(3000, 2400),
        key_size=0.5,
        notes="Ein Shroud als enginePylon statt als fuselage.",
    ),

    # --------------------------------- Folie 19: bewusst gleiches Format und Licht
    Shot(
        name="closeup_vessel",
        include=("s-ivb_lh2",),
        # The cutting plane has to contain the vehicle axis and open towards
        # the camera; along Y the shot showed either a flat plate or a closed
        # shell, depending on the sign.
        section=(1.0, 0.0, 0.0),
        direction=(0.60, -1.0, 0.35),
        resolution=(2400, 2400),
        key_size=0.5,
        notes="Folie 19, links. Halbschnitt, sonst ist der Vessel eine "
              "merkmalslose Kapsel.",
    ),
    Shot(
        name="closeup_system",
        include=("s-ic_fuelFeed", "s-ic_loxFeed"),
        direction=(0.60, -1.0, 0.35),
        resolution=(2400, 2400),
        key_size=0.5,
        notes="Folie 19, Mitte. Beide Kreise, damit der Ausschnitt dem "
              "Datensatz entspricht.",
    ),

    # ----------------------------------------- Systeme fuer Pfeilbeschriftung
    # Reine Seitenansicht: direction.z = 0, sonst kippt die Kamera nach oben
    # und die Leitungen laufen perspektivisch auseinander. Orthographisch,
    # damit gleich hohe Bauteile im Bild gleich hoch bleiben und ein Pfeil auf
    # der Folie dorthin zeigt, wo das Bauteil wirklich sitzt.
    Shot(
        name="systems_side",
        include=("s-ic*", "engines"),
        ghost=("fuselage", "wing", "enginePylon", "fuelTank", "baffle"),
        ghost_alpha=0.06,
        ghost_flat=True,
        direction=(0.0, -1.0, 0.0),
        ortho=True,
        orientation="vertical",
        resolution=(2400, 3600),
        key_size=1.0,
        margin=1.12,
        notes="Systeme der S-IC von der Seite, Struktur nur als Kontur. "
              "Grundlage fuer die Pfeilbeschriftung auf der Systems-Folie.",
    ),
    Shot(
        name="systems_side_bare",
        include=("s-ic_fuelFeed", "s-ic_loxFeed", "s-ic_loxPressurization",
                 "s-ic_ordenance", "s-ic_flightControl", "engines"),
        direction=(0.0, -1.0, 0.0),
        ortho=True,
        orientation="vertical",
        resolution=(2400, 3600),
        key_size=0.7,
        margin=1.12,
        notes="Wie systems_side, aber ohne jede Struktur. Falls die "
              "Konturen die Pfeile stoeren.",
    ),
    Shot(
        name="closeup_deck",
        include=("apolloSeats",),
        direction=(0.60, -1.0, 0.35),
        resolution=(2400, 2400),
        key_size=0.5,
        notes="Folie 19, rechts. Existiert erst nach Ergänzung der deck seats.",
    ),

    # ------------------------------------------ Titel- und Abschnittsfolien
    # Drei der vier Bilder teilen sich Neigung, Blickrichtung und Licht: die
    # Abschnittsfolien sollen als eine Serie lesbar sein, in der sich nur der
    # Ausschnitt und das hervorgehobene Bauteil ändern.
    Shot(
        name="slide_title",
        ghost=("fuselage", "wing", "enginePylon"),
        direction=(0.50, -1.0, 0.16),
        resolution=(1000, 3600),
        key_size=1.8,
        orientation="vertical",
        notes="Titelfolie. Rakete aufrecht, Struktur durchscheinend, damit "
              "alle Komponenten im Inneren sichtbar bleiben.",
    ),
    Shot(
        name="slide_demonstrator",
        ghost=("fuselage", "wing", "enginePylon"),
        # Deutlich dichter als slide_title: die Struktur soll als Huelle
        # lesbar bleiben und nicht nur als Kante. Ohne ghost_flat behaelt sie
        # ihre Schattierung, sonst wirkt sie wie aufgemalt.
        ghost_alpha=0.26,
        # Groessere Rauheit streut das Glanzlicht der Flaechenleuchte, statt
        # es als scharfen Ring auf der Domkuppe abzubilden. Metallic auf 0,
        # weil schon ein kleiner Metallanteil den Ring zurueckholt.
        style_overrides={
            "fuelTank": {"roughness": 0.62, "metallic": 0.0},
            "fuselage": {"roughness": 0.55},
        },
        # Lange Brennweite: die Kameradistanz folgt der Brennweite, ein Tele
        # rueckt sie also weit genug weg, dass Spitze und Triebwerke nicht
        # mehr nach hinten wegkippen. Der Ausschnitt bleibt derselbe.
        # Orthographisch waere die Achse voellig gerade, nimmt dem Bild aber
        # auch die Verjuengung, die ihm Tiefe gibt.
        lens=300.0,
        direction=(0.62, -1.0, 0.22),
        resolution=(1300, 3600),
        key_size=2.4,
        orientation="vertical",
        notes="Demonstrator-Folie. Wie slide_title, aber Struktur dichter, "
              "weicheres Glanzlicht und flachere Perspektive.",
    ),
    Shot(
        name="slide_overview",
        ghost=("fuselage", "wing", "enginePylon"),
        direction=SLIDE_DIRECTION,
        resolution=(4800, 2000),
        key_size=1.8,
        orientation="horizontal",
        tilt=SLIDE_TILT,
        notes="Abschnittsfolie Gesamtkonzept. Gleiche Lage wie slide_tanks "
              "und slide_systems.",
    ),
    Shot(
        name="slide_tanks",
        include=("fuelTank", "baffle"),
        ghost=("fuelTank",),
        ghost_alpha=0.22,
        direction=SLIDE_DIRECTION,
        resolution=(4800, 2000),
        key_size=1.8,
        orientation="horizontal",
        tilt=SLIDE_TILT,
        notes="Abschnittsfolie Tanks. Wie tanks_ghost, aber mit angehobener "
              "Spitze.",
    ),
    Shot(
        name="slide_systems",
        # Die Stufe als Ganzes: alle s-ic-uIDs plus der F-1-Cluster, der als
        # "engines" ausserhalb des Namensschemas liegt.
        include=("s-ic*", "engines"),
        # Alles ausser genericSystem verschwindet fast: Struktur, Finnen,
        # Shrouds, Tanks und Schwallwaende bleiben nur als Kontur stehen, in
        # der die Leitungen und Triebwerke liegen.
        ghost=("fuselage", "wing", "enginePylon", "fuelTank", "baffle"),
        ghost_alpha=0.06,
        ghost_flat=True,
        direction=SLIDE_DIRECTION,
        resolution=(4200, 2400),
        key_size=1.0,
        orientation="horizontal",
        tilt=SLIDE_TILT,
        notes="Abschnittsfolie Systeme. Closeup der S-IC in der Lage von "
              "slide_tanks, Fokus auf engines, Leitungen und die uebrigen "
              "genericSystems.",
    ),
]


# --------------------------------------------------------------------------
# Colour handling
# --------------------------------------------------------------------------


def srgb_to_linear(channel: float) -> float:
    """Blender expects linear values; the palette is given in sRGB."""
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def hex_to_rgba(value: str, alpha: float = 1.0) -> tuple[float, ...]:
    value = value.lstrip("#")
    rgb = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return (*[srgb_to_linear(c) for c in rgb], alpha)


# --------------------------------------------------------------------------
# Scene assembly
# --------------------------------------------------------------------------


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_stl(path: Path):
    """Import one STL and return the created object.

    Blender renamed the operator in 4.1; both spellings are tried so the
    script keeps working across versions.
    """
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:  # Blender < 4.1
        bpy.ops.import_mesh.stl(filepath=str(path))
    created = set(bpy.data.objects) - before
    if not created:
        raise RuntimeError(f"Import produced no object: {path.name}")
    if len(created) > 1:
        # A wallSegment compound can arrive as several shells; join them so the
        # component stays one object and one manifest entry.
        objects = sorted(created, key=lambda o: o.name)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
        return objects[0]
    return created.pop()


def make_material(name: str, style: dict, alpha: float = 1.0,
                  flat: bool = False):
    """Material for one component.

    :param flat: drop the specular response. A translucent shell still catches
        highlights, and stacked over a whole stage those blooms turn into a
        milky veil that costs the components behind it more contrast than the
        tint itself. Without them the ghost reads as a pure colour wash.
    """
    key = f"{name}__{alpha:.2f}{'__flat' if flat else ''}"
    if key in bpy.data.materials:
        return bpy.data.materials[key]

    mat = bpy.data.materials.new(key)
    if not mat.node_tree:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = hex_to_rgba(style["color"])
    bsdf.inputs["Roughness"].default_value = style.get("roughness", 0.4)
    bsdf.inputs["Metallic"].default_value = style.get("metallic", 0.2)
    if flat:
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.9
        # Renamed across Blender versions, absent in none of the supported
        # ones -- but cheap enough to guard.
        for socket in ("Specular IOR Level", "Specular"):
            if socket in bsdf.inputs:
                bsdf.inputs[socket].default_value = 0.0
                break
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        # Blender 4.2 replaced blend_method with a surface render method.
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        else:
            mat.blend_method = "BLEND"
            mat.show_transparent_back = False
    return mat


def shade_smooth_by_angle(obj, angle: float) -> None:
    """Smooth shading with a sharp-edge threshold, across Blender versions.

    ``shade_smooth_by_angle`` exists from Blender 4.1; before that the same
    result came from the mesh-level auto-smooth flag.
    """
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if hasattr(bpy.ops.object, "shade_smooth_by_angle"):
        bpy.ops.object.shade_smooth_by_angle(angle=angle)
    else:  # Blender < 4.1
        bpy.ops.object.shade_smooth()
        obj.data.use_auto_smooth = True
        obj.data.auto_smooth_angle = angle
    obj.select_set(False)


def load_components(shot: Shot | None = None) -> list[dict]:
    """Import the components a shot needs.

    Importing all 37 components and hiding most of them again costs several
    seconds per shot at fine tessellation, so the manifest is filtered before
    anything is read from disk.
    """
    if not MANIFEST.is_file():
        raise SystemExit(
            f"Manifest not found: {MANIFEST}\n"
            "Run scripts/export_models.py first."
        )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if shot is not None:
        manifest = [e for e in manifest if wanted(e, shot)]

    components = []
    for entry in manifest:
        path = MODEL_DIR / entry["file"]
        if not path.is_file():
            print(f"  missing, skipped: {entry['file']}")
            continue
        obj = import_stl(path)
        obj.name = entry["uid"]
        obj.data.name = entry["uid"]

        style = dict(CATEGORY_STYLE.get(entry["category"], FALLBACK_STYLE))
        style.update(UID_STYLE.get(entry["uid"], {}))
        if shot is not None:
            style.update(shot.style_overrides.get(entry["category"], {}))
            style.update(shot.style_overrides.get(entry["uid"], {}))

        obj.data.materials.clear()
        obj.data.materials.append(
            make_material(entry["uid"], style, alpha=1.0))

        # Smooth shading with an angle threshold keeps the cylinder-to-dome
        # junction crisp while the rotational surfaces stay smooth.
        shade_smooth_by_angle(obj, math.radians(35))

        components.append({**entry, "object": obj, "style": style})
        print(f"  loaded [{entry['category']:>14}] {entry['uid']}")

    return components


def wanted(entry: dict, shot: Shot) -> bool:
    component = {"uid": entry["uid"], "category": entry["category"]}
    if shot.include and not matches(component, shot.include):
        return False
    if shot.exclude and matches(component, shot.exclude):
        return False
    return True


# --------------------------------------------------------------------------
# Orientation, selection, section cut
# --------------------------------------------------------------------------


def world_bounds(objects) -> tuple[Vector, Vector]:
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def orient_model(objects, up_axis: str) -> None:
    """Rotate the whole model so the vehicle axis points up.

    TiGL writes the STL in CPACS global coordinates. Which axis the stack runs
    along depends on the transformations in the dataset, so ``auto`` derives it
    from the bounding box instead of hard-coding an assumption.
    """
    if up_axis == "none":
        return
    if up_axis == "auto":
        lo, hi = world_bounds(objects)
        extent = hi - lo
        up_axis = "xyz"[max(range(3), key=lambda i: extent[i])]
    if up_axis == "z":
        return

    angle = math.radians(90)
    if up_axis == "x":
        axis, value = "Y", angle
    elif up_axis == "y":
        axis, value = "X", -angle
    else:
        raise ValueError(f"unknown up_axis: {up_axis}")

    matrix = Matrix.Rotation(value, 4, axis)
    for obj in objects:
        obj.matrix_world = matrix @ obj.matrix_world


def center_model(objects) -> None:
    lo, hi = world_bounds(objects)
    offset = -(lo + hi) / 2.0
    matrix = Matrix.Translation(offset)
    for obj in objects:
        obj.matrix_world = matrix @ obj.matrix_world


def lay_down(objects) -> None:
    """Turn the vehicle axis from vertical to horizontal.

    Applied after orient_model, which has already put the long axis along Z.
    """
    matrix = Matrix.Rotation(math.radians(90), 4, "Y")
    for obj in objects:
        obj.matrix_world = matrix @ obj.matrix_world


def tilt_up(objects, degrees: float) -> None:
    """Lift the nose out of the horizontal.

    Applied after lay_down, which has left the vehicle axis along +X with the
    nose towards +X. A negative rotation about Y raises that end. The frame's
    vertical is world Z, so the apparent tilt in the image is a little smaller
    than the angle given here: the standard camera direction already looks
    slightly down on the model.
    """
    matrix = Matrix.Rotation(math.radians(-degrees), 4, "Y")
    for obj in objects:
        obj.matrix_world = matrix @ obj.matrix_world


def matches(component: dict, names: tuple[str, ...]) -> bool:
    """A shot selector matches either a uID or a category name.

    Selectors may use shell wildcards, so that a whole stage can be addressed
    as ``s-ic*`` instead of listing its twenty uIDs. No uID contains a glob
    character, so plain names keep matching exactly as before.
    """
    if component["uid"] in names or component["category"] in names:
        return True
    return any(fnmatch(component["uid"], name)
               or fnmatch(component["category"], name) for name in names)


def apply_visibility(components: list[dict], shot: Shot) -> list[dict]:
    visible = []
    for component in components:
        obj = component["object"]
        show = True
        if shot.include and not matches(component, shot.include):
            show = False
        if shot.exclude and matches(component, shot.exclude):
            show = False
        obj.hide_render = not show
        obj.hide_viewport = not show
        if show:
            visible.append(component)

        if show and shot.ghost and matches(component, shot.ghost):
            obj.data.materials.clear()
            obj.data.materials.append(
                make_material(component["uid"], component["style"],
                              alpha=shot.ghost_alpha, flat=shot.ghost_flat))
        elif show:
            obj.data.materials.clear()
            obj.data.materials.append(
                make_material(component["uid"], component["style"], alpha=1.0))
    return visible


def apply_section(visible: list[dict], normal: tuple[float, float, float]) -> None:
    """Cut every visible solid with a half space.

    OCCT lofts are closed and manifold, so the exact boolean solver caps the
    cut faces and the interior reads as a proper section rather than a hollow
    shell. Open shells — the wallSegment baffles — cannot be cut this way and
    are left whole, which is what you want: they are meant to be visible
    inside the cut tank.
    """
    lo, hi = world_bounds([c["object"] for c in visible])
    size = max(hi - lo) * 4.0
    center = (lo + hi) / 2.0

    bpy.ops.mesh.primitive_cube_add(size=size, location=center)
    cutter = bpy.context.active_object
    cutter.name = "SectionCutter"
    direction = Vector(normal).normalized()
    cutter.location = center + direction * (size / 2.0)
    cutter.hide_render = True
    cutter.hide_viewport = True

    for component in visible:
        if component["category"] == "baffle":
            continue
        obj = component["object"]
        modifier = obj.modifiers.new(name="Section", type="BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.solver = "EXACT"
        modifier.object = cutter


# --------------------------------------------------------------------------
# Camera and light
# --------------------------------------------------------------------------


def camera_extents(objects, direction: Vector) -> tuple[float, float, float, Vector]:
    """Extent of the subject in camera space.

    Framing on the bounding sphere wastes most of the frame for a slender
    object such as the escape tower: the sphere is driven by the long axis
    while the silhouette is narrow. Projecting the bounding-box corners onto
    the camera's right and up vectors gives the extent that actually has to
    fit, separately per axis.

    :return: half width, half height, half depth, and the projected centre.
    """
    forward = -direction.normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    if abs(forward.dot(world_up)) > 0.999:  # looking straight down the axis
        world_up = Vector((0.0, 1.0, 0.0))
    right = forward.cross(world_up).normalized()
    up = right.cross(forward).normalized()

    spans = project_vertices(objects, right, up, forward)
    if spans is None:  # numpy unavailable, fall back to the bounding box
        points = [obj.matrix_world @ Vector(corner)
                  for obj in objects for corner in obj.bound_box]
        spans = [[p.dot(axis) for p in points] for axis in (right, up, forward)]
        spans = [(min(v), max(v)) for v in spans]

    (x0, x1), (y0, y1), (z0, z1) = spans
    centre = (right * ((x0 + x1) / 2.0) + up * ((y0 + y1) / 2.0)
              + forward * ((z0 + z1) / 2.0))
    return ((x1 - x0) / 2.0, (y1 - y0) / 2.0, (z1 - z0) / 2.0, centre)


def project_vertices(objects, right: Vector, up: Vector, forward: Vector):
    """Extent of the actual silhouette along the three camera axes.

    Projecting bounding-box corners overstates the extent whenever the camera
    is tilted: the corners of a box sit well outside the silhouette of the
    body inside it, and the frame then reserves room for geometry that is not
    there. Measuring the vertices themselves costs a numpy pass and gives the
    real figure.

    :return: [(min, max)] per axis, or None if numpy is unavailable.
    """
    try:
        import numpy as np
    except ImportError:
        return None

    axes = np.array([list(right), list(up), list(forward)]).T
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)

    for obj in objects:
        mesh = obj.data
        count = len(mesh.vertices)
        if not count:
            continue
        flat = np.empty(count * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", flat)
        local = flat.reshape(-1, 3)

        matrix = np.array(obj.matrix_world)
        world = local @ matrix[:3, :3].T + matrix[:3, 3]

        projected = world @ axes
        lo = np.minimum(lo, projected.min(axis=0))
        hi = np.maximum(hi, projected.max(axis=0))

    if not np.isfinite(lo).all():
        return None
    return list(zip(lo.tolist(), hi.tolist()))


def add_camera(visible: list[dict], shot: Shot):
    objects = [c["object"] for c in visible]
    direction = Vector(shot.direction).normalized()
    half_w, half_h, half_d, centre = camera_extents(objects, direction)
    half_w = max(half_w, 1e-3)
    half_h = max(half_h, 1e-3)
    radius = max(Vector((half_w, half_h, half_d)).length, 1e-3)

    res_x, res_y = shot.resolution
    aspect = res_x / res_y

    camera_data = bpy.data.cameras.new("Camera")
    # Fixing the sensor to the horizontal axis makes the field of view
    # independent of the output aspect ratio, so the arithmetic below holds
    # for portrait and landscape shots alike.
    camera_data.sensor_fit = "HORIZONTAL"

    if shot.ortho:
        camera_data.type = "ORTHO"
        # ortho_scale covers the horizontal extent; the vertical one has to be
        # converted through the aspect ratio before comparing.
        camera_data.ortho_scale = 2.0 * shot.margin * max(half_w, half_h * aspect)
        distance = radius * 6.0
    else:
        camera_data.type = "PERSP"
        camera_data.lens = shot.lens
        tan_x = camera_data.sensor_width / 2.0 / shot.lens
        tan_y = tan_x / aspect
        # Distance at which both extents fit, plus half the depth so that the
        # near side of the subject is not already inside the frustum edge.
        distance = shot.margin * max(half_w / tan_x, half_h / tan_y) + half_d

    camera_data.clip_start = max(distance - radius * 4.0, 0.01)
    camera_data.clip_end = distance + radius * 8.0

    camera = bpy.data.objects.new("Camera", camera_data)
    camera.location = centre + direction * distance
    camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def add_lighting(visible: list[dict], shot: Shot) -> None:
    """Three-point setup scaled to the model, plus a neutral world."""
    objects = [c["object"] for c in visible]
    lo, hi = world_bounds(objects)
    center = (lo + hi) / 2.0
    radius = max((hi - lo).length / 2.0, 1e-3)

    world = bpy.data.worlds.new("World")
    if not world.node_tree:
        world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.55, 0.60, 0.64, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.55
    bpy.context.scene.world = world

    # Size drives shadow softness, not brightness: an area light's power is
    # the total emitted, so shrinking the key sharpens the shadows without
    # darkening the scene. The fill stays large on purpose, it is only there
    # to lift the shadow side.
    lights = [
        ("Key", Vector((1.0, -1.1, 0.9)), 4.2, shot.key_size),
        ("Fill", Vector((-1.2, -0.7, 0.25)), 1.1, 3.0),
        ("Rim", Vector((-0.4, 1.2, 0.8)), 2.2, 1.2),
    ]
    for name, direction, strength, size in lights:
        data = bpy.data.lights.new(name, type="AREA")
        data.shape = "DISK"
        data.size = max(radius * size, 1e-3)
        # Area light power scales with the square of the distance; tying it to
        # the model radius keeps the exposure constant across shots that frame
        # a whole launcher and shots that frame a single valve.
        data.energy = strength * (radius ** 2) * 40.0
        light = bpy.data.objects.new(name, data)
        light.location = center + direction.normalized() * radius * 3.0
        light.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
        bpy.context.collection.objects.link(light)


# --------------------------------------------------------------------------
# Render settings
# --------------------------------------------------------------------------


def setup_freestyle(shot: Shot) -> None:
    """Outline pass over the shaded image.

    The edges keep the geometry readable when a projector eats the contrast.
    Freestyle is optional, though: if anything here fails the shot should
    still render, so the whole block is guarded.
    """
    try:
        view_layer = bpy.context.view_layer
        view_layer.use_freestyle = True
        view_layer.freestyle_settings.crease_angle = math.radians(140)

        linesets = view_layer.freestyle_settings.linesets
        if not linesets:
            linesets.new("Edges")
        lineset = linesets[0]
        lineset.select_silhouette = True
        lineset.select_crease = True
        lineset.select_border = True

        # Blender 5.0 no longer creates a line style along with the lineset.
        style = lineset.linestyle
        if style is None:
            style = bpy.data.linestyles.new("SaturnV")
            lineset.linestyle = style

        style.color = (0.10, 0.12, 0.14)
        # Roughly one pixel at 2200 px width; scales with the output size.
        style.thickness = max(1.0, shot.resolution[0] / 2200.0)
    except Exception as exc:  # noqa: BLE001
        print(f"  Freestyle deaktiviert ({exc})")
        bpy.context.scene.render.use_freestyle = False


def configure_render(shot: Shot, engine: str, samples: int) -> None:
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = shot.resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 15

    available = {item.identifier
                 for item in scene.render.bl_rna.properties["engine"].enum_items}
    if engine == "EEVEE":
        engine = ("BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available
                  else "BLENDER_EEVEE")
    scene.render.engine = engine

    if scene.render.engine.startswith("BLENDER_EEVEE"):
        scene.eevee.taa_render_samples = samples
        # Ambient occlusion is what makes the domes and the feed lines read as
        # bodies rather than flat silhouettes. In EEVEE Next it comes with the
        # raytracing switch, in legacy EEVEE it is its own flag.
        if hasattr(scene.eevee, "use_raytracing"):
            scene.eevee.use_raytracing = True
        elif hasattr(scene.eevee, "use_gtao"):
            scene.eevee.use_gtao = True
            scene.eevee.gtao_distance = 2.0
    else:
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True

    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    scene.render.use_freestyle = shot.freestyle
    if shot.freestyle:
        setup_freestyle(shot)


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


@contextlib.contextmanager
def quiet_render():
    """Swallow Freestyle's per-edge chatter while rendering.

    Freestyle prints one "edge N - M appears twice" line per duplicated edge,
    and in an STL tessellation adjacent triangles never share vertices, so
    every edge is duplicated. For the whole vehicle that is millions of lines
    on stdout. The messages come from C code writing to the file descriptor
    directly, so Blender's logging levels cannot suppress them -- the
    descriptor itself has to be redirected. Everything that is not this
    specific warning is printed afterwards, so real errors still surface.
    """
    # Blender replaces sys.__stdout__ in background mode, so asking it for a
    # descriptor silently fails and the filter never runs. Descriptor 1 is the
    # one Freestyle's C++ code writes to, so address it directly.
    fd = 1
    try:
        saved = os.dup(fd)
    except OSError:  # no usable stdout, e.g. embedded without a console
        yield
        return

    buffer = tempfile.TemporaryFile(mode="w+b")
    try:
        sys.stdout.flush()
        os.dup2(buffer.fileno(), fd)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, fd)
        os.close(saved)

        buffer.seek(0)
        noise = 0
        for raw in buffer:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if "appears twice, correcting" in line:
                noise += 1
                continue
            if line.strip():
                print(line)
        buffer.close()
        if noise:
            print(f"  ({noise:,} Freestyle-Kantenwarnungen unterdrueckt)")


def report_framing(path: Path) -> None:
    """State how much of the frame the subject actually fills.

    Saves guessing from a downscaled preview when tuning margin or lens.
    """
    try:
        import numpy as np
        image = bpy.data.images.load(str(path))
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        alpha = pixels.reshape(height, width, 4)[:, :, 3]
        bpy.data.images.remove(image)

        rows = np.where(alpha.max(axis=1) > 0.01)[0]
        cols = np.where(alpha.max(axis=0) > 0.01)[0]
        if not len(rows) or not len(cols):
            print("  Bild ist leer -- Kamera oder Auswahl pruefen")
            return
        fill_h = (rows[-1] - rows[0] + 1) / height * 100
        fill_w = (cols[-1] - cols[0] + 1) / width * 100
        print(f"  Motiv fuellt {fill_w:.0f} % der Breite, {fill_h:.0f} % der Hoehe")
    except Exception as exc:  # noqa: BLE001
        print(f"  Framing-Messung uebersprungen ({exc})")


def render_shot(shot: Shot, engine: str, samples: int, do_render: bool) -> bool:
    print(f"\n--- {shot.name} ---")
    clear_scene()
    components = load_components(shot)

    visible = apply_visibility(components, shot)
    if not visible:
        selectors = ", ".join(shot.include) or "(alle)"
        print(f"  no matching component for: {selectors} — shot skipped")
        return False

    orient_model([c["object"] for c in visible], shot.up_axis)
    center_model([c["object"] for c in visible])

    if shot.orientation == "horizontal":
        lay_down([c["object"] for c in visible])
        if shot.tilt:
            tilt_up([c["object"] for c in visible], shot.tilt)
        center_model([c["object"] for c in visible])

    if shot.section:
        apply_section(visible, shot.section)

    add_camera(visible, shot)
    add_lighting(visible, shot)
    configure_render(shot, engine, samples)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / f"{shot.name}.png"
    bpy.context.scene.render.filepath = str(out_file)

    if not do_render:
        print(f"  scene prepared, not rendered ({len(visible)} components)")
        return True

    with quiet_render():
        bpy.ops.render.render(write_still=True)
    print(f"  written: {out_file}")
    report_framing(out_file)
    return True


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="render_saturnv")
    parser.add_argument("--shots", default="",
                        help="comma separated shot names, default all")
    parser.add_argument("--engine", default="EEVEE",
                        choices=["EEVEE", "CYCLES"])
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--no-render", action="store_true",
                        help="build the scene but do not render")
    parser.add_argument("--list", action="store_true",
                        help="list the available shots and exit")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    if args.list:
        width = max(len(s.name) for s in SHOTS)
        for shot in SHOTS:
            print(f"{shot.name:<{width}}  {shot.notes}")
        return

    wanted = [s.strip() for s in args.shots.split(",") if s.strip()]
    unknown = set(wanted) - {s.name for s in SHOTS}
    if unknown:
        raise SystemExit(f"unknown shot(s): {', '.join(sorted(unknown))}")
    shots = [s for s in SHOTS if not wanted or s.name in wanted]

    done = 0
    for shot in shots:
        if render_shot(shot, args.engine, args.samples, not args.no_render):
            done += 1

    print(f"\n{'=' * 60}")
    print(f"{done} / {len(shots)} shots processed, output in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()