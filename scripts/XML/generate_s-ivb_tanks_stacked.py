#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate the CPACS ``<fuelTank>`` elements for the Saturn V S-IVB stage --
stacked variant, in which the two tanks do not overlap.

Run with::

    uv run generate_sivb_tanks_stacked.py                 # ./s-ivb_fuelTanks_stacked.xml
    uv run generate_sivb_tanks_stacked.py --stdout
    uv run generate_sivb_tanks_stacked.py --refs

This is the comparison case to ``generate_sivb_tanks.py``.  All stations, the
dome contour and the LOX tank are identical; the difference is only how the LH2
tank is represented:

    nested variant   s-ivb_lh2 is the complete welded propellant tank, the LOX
                     lens sits inside it, the two solids overlap and the LH2
                     compartment is the difference of the two.
    stacked variant  s-ivb_lh2 is the LH2 compartment itself.  Its aft closure
                     follows the aft dome inward to the attach ring and then
                     turns back up along the common bulkhead, so the two solids
                     touch on the shared bulkhead surface and nowhere overlap.

The stacked variant costs the parametric ``domeType`` branch for the LH2 tank:
the aft closure is re-entrant, so both tanks now need sections and segments.  In
exchange the geometric volumes are directly comparable to the documented figures
without subtracting anything.

The geometry, its sources and the derivation of the 117.41 in ring radius are
documented in ``generate_sivb_tanks.py``; only the axial layout is repeated
here::

    STA 3222.56  ---.---            forward dome apex = IU interface
                    |  )
    STA 3100.56  ---+---            forward dome tangent = fwd skirt joint
                    |   |
                    |   |           barrel, 268.56 in           LH2 compartment
                    |   |
    STA 2889.82     |-.-|           common bulkhead apex
    STA 2832.00  ---+(-)+---        aft dome tangent = aft skirt joint
                    |( )|
    STA 2779.63     |+-+|           attach ring, r = 117.41 in
    STA 2710.04  ---'---            aft dome apex           LOX tank

LH2 meridian, in section order: bulkhead apex, down the bulkhead to the attach
ring, kink, out along the aft dome to its tangent plane, up the barrel, over the
forward dome to its apex.  The station coordinate is therefore not monotonic,
which is legal -- sections are profiles placed in space.

Both vessels are lofted C0.  ``CCPACSVessel::BuildShapeFromSegments`` takes the
continuity from the first segment, and ``CTiglAbstractSegment`` initialises
``_continuity`` to ``C0`` and never overwrites it, because ``loftContinuity``
exists on ``fuselageType``, ``wingType`` and ``ductType`` but not on
``vesselType``.  ``CTiglMakeLoft`` then calls ``SetMaxDegree(1)``, so consecutive
profiles are joined by ruled surfaces: the kink at the attach ring comes for
free, but every dome is a cone frustum chain and the meridian accuracy is set by
the section counts alone.  The report prints the resulting deviation.

Because the bulkhead surface is generated twice -- once as the forward closure of
the LOX tank, once as the aft closure of the LH2 tank -- both use the same
meridian sampling, so the two lofts coincide exactly.

Sources: see ``generate_sivb_tanks.py``; ``--refs`` prints the header entries.
"""

from __future__ import annotations

import argparse
import math
import sys
from xml.etree import ElementTree as ET

# =============================================================================
# CONFIGURATION -- keep in step with generate_sivb_tanks.py
# =============================================================================

IN2M = 0.0254

STA_AFT_TANGENT = 2832.00
STA_FWD_TANGENT = 3100.56

PARENT_UID = "s-ivb_aftInterstageAssembly"
PARENT_STATION = 2519.00

CYLINDER_RADIUS_IN = 130.0
DOME_HALF_AXIS_FRACTION = 122.0 / 130.0

# Attach ring of the common bulkhead on the aft dome, solved from the documented
# LOX volume; see generate_sivb_tanks.py.
LOX_RING_STATION = 2779.63

# Sections per full dome quadrant, equally spaced in meridian angle.  The aft
# dome pieces get a proportional share of this, so the angular step is the same
# everywhere.
DOME_SECTIONS = 12

# Intermediate stations along the barrel, as a fraction of its length.  The loft
# is ruled, so a straight barrel needs none; these only give evenly spaced
# control sections.
BARREL_SAMPLE_FRACTIONS = [0.5]

APEX_RADIUS_M = 0.00001

V_LOX_DOC_FT3 = 2830.0
V_LH2_DOC_FT3 = 10418.0

NAME_TAG = "name"
PROFILE_UID = "circularProfile"

LOX_TANK_UID = "s-ivb_oxidizer"
LOX_VESSEL_UID = "s-ivb_lox_vessel"
LH2_TANK_UID = "s-ivb_lh2"
LH2_VESSEL_UID = "s-ivb_lh2_vessel"

INDENT = "    "
BASE_INDENT_LEVELS = 5

NEW_REFERENCES = """\
        [5] Saturn V Flight Manual, SA-503 / SA-507. MSFC-MAN-503 (1 Nov 1968) /
            MSFC-MAN-507 (15 Aug 1969), Marshall Space Flight Center, Huntsville,
            AL. Section VI, Figure 6-1: S-IVB Stage Structure.
        [6] McCutcheon, K.D. U.S. Manned Rocket Propulsion Evolution, Part 8.30:
            The Saturn S-IVB Stage. Aircraft Engine Historical Society,
            rev. 25 Jul 2024.
            https://www.enginehistory.org/Rockets/RPE08.30/RPE08.30.shtml
        [7] S-IVB (Saturn V) Overview. heroicrelics.org; structural breakdown and
            manufacturing flow sequence.
            http://heroicrelics.org/info/s-ivb/s-ivb-v-overview.html
        [8] Osterhout, W.L., Jr. (dir.). Saturn S-IV / S-IVB Data Summary
            Handbook. Douglas Aircraft Company, Missile & Space Systems Division,
            Saturn Systems Development, prepared by Logistics Support
            Publications, 1 October 1965. NASA accession N66-28064, 164 pp.
            Archival copy: Saturn History Document, University of Alabama
            Research Institute, History of Science & Technology Group, M. Louis
            Salmon Library, University of Alabama in Huntsville.
            Fig. 24 Saturn IB configuration (NASA stations); Fig. 25 S-IVB/IB
            inboard profile; Fig. 27 S-IVB common bulkhead; Fig. 28 manufacturing
            plan; p. 54 S-IVB structures."""


# =============================================================================
# GEOMETRY
# =============================================================================


class Geometry:
    """Resolved axial layout of the S-IVB tank assembly; lengths in inches."""

    def __init__(self) -> None:
        self.R = CYLINDER_RADIUS_IN
        self.h_dome = self.R * DOME_HALF_AXIS_FRACTION

        self.x_aft_tangent = STA_AFT_TANGENT
        self.x_fwd_tangent = STA_FWD_TANGENT
        self.L_barrel = self.x_fwd_tangent - self.x_aft_tangent

        self.x_aft_apex = self.x_aft_tangent - self.h_dome
        self.x_fwd_apex = self.x_fwd_tangent + self.h_dome

        self.x_ring = LOX_RING_STATION
        u = (self.x_aft_tangent - self.x_ring) / self.h_dome
        if not 0.0 <= u <= 1.0:
            raise ValueError("LOX_RING_STATION must lie on the aft dome.")
        self.ring_u = u
        self.a_ring = self.R * math.sqrt(max(0.0, 1.0 - u * u))
        self.b_cap = DOME_HALF_AXIS_FRACTION * self.a_ring
        self.x_cap_apex = self.x_ring + self.b_cap
        self.theta_ring_deg = math.degrees(math.acos(u))

    # -- volumes --------------------------------------------------------------

    def v_lox_geom(self) -> float:
        u = self.ring_u
        seg = math.pi * self.R**2 * self.h_dome * (2.0 / 3.0 - u + u**3 / 3.0)
        cap = (2.0 / 3.0) * math.pi * self.a_ring**2 * self.b_cap
        return seg + cap

    def v_envelope_geom(self) -> float:
        return math.pi * self.R**2 * self.L_barrel + (4.0 / 3.0) * math.pi * (
            self.R**2 * self.h_dome
        )

    def v_lh2_geom(self) -> float:
        return self.v_envelope_geom() - self.v_lox_geom()

    # -- meridian -------------------------------------------------------------

    def aft_dome_point(self, theta_deg: float) -> tuple[float, float]:
        """Aft dome of the tank: 0 deg at the apex, 90 deg at the tangent plane."""
        t = math.radians(theta_deg)
        return self.x_aft_tangent - self.h_dome * math.cos(t), self.R * math.sin(t)

    def fwd_dome_point(self, theta_deg: float) -> tuple[float, float]:
        """Forward dome: 0 deg at the apex, 90 deg at the tangent plane."""
        t = math.radians(theta_deg)
        return self.x_fwd_tangent + self.h_dome * math.cos(t), self.R * math.sin(t)

    def cap_point(self, phi_deg: float) -> tuple[float, float]:
        """Common bulkhead: 0 deg at the apex, 90 deg at the attach ring."""
        t = math.radians(phi_deg)
        return self.x_ring + self.b_cap * math.cos(t), self.a_ring * math.sin(t)

    def _cap_angles(self) -> list[float]:
        """Sampling of the bulkhead, apex to ring; shared by both tanks."""
        return [90.0 * i / DOME_SECTIONS for i in range(DOME_SECTIONS + 1)]

    def lox_contour(self) -> list[tuple[float, float, str]]:
        """Aft apex, up the aft dome to the ring, back along the bulkhead."""
        pts: list[tuple[float, float, str]] = []
        n = DOME_SECTIONS
        for i in range(n + 1):
            theta = self.theta_ring_deg * i / n
            x, r = self.aft_dome_point(theta)
            note = (
                "Aft dome apex."
                if i == 0
                else (
                    "Attach ring: common bulkhead welded to the aft dome; meridian kink."
                    if i == n
                    else f"Aft dome at {theta:.2f} deg meridian angle."
                )
            )
            pts.append((x, r, note))
        for phi in reversed(self._cap_angles()[:-1]):
            x, r = self.cap_point(phi)
            note = (
                "Common bulkhead apex."
                if phi == 0.0
                else f"Common bulkhead at {phi:.2f} deg meridian angle."
            )
            pts.append((x, r, note))
        return pts

    def lh2_contour(self) -> list[tuple[float, float, str]]:
        """Bulkhead apex, down to the ring, out along the aft dome, up and over."""
        pts: list[tuple[float, float, str]] = []
        for phi in self._cap_angles():
            x, r = self.cap_point(phi)
            note = (
                "Common bulkhead apex; aft closure is re-entrant."
                if phi == 0.0
                else (
                    "Attach ring: common bulkhead meets the aft dome; meridian kink."
                    if phi == 90.0
                    else f"Common bulkhead at {phi:.2f} deg meridian angle."
                )
            )
            pts.append((x, r, note))
        # remaining piece of the aft dome, from the ring out to the tangent plane
        n_aft = max(1, round(DOME_SECTIONS * (90.0 - self.theta_ring_deg) / 90.0))
        for i in range(1, n_aft + 1):
            theta = self.theta_ring_deg + (90.0 - self.theta_ring_deg) * i / n_aft
            x, r = self.aft_dome_point(theta)
            note = (
                "Aft dome tangent plane; aft skirt joint."
                if i == n_aft
                else f"Aft dome at {theta:.2f} deg meridian angle."
            )
            pts.append((x, r, note))
        for f in BARREL_SAMPLE_FRACTIONS:
            pts.append(
                (
                    self.x_aft_tangent + f * self.L_barrel,
                    self.R,
                    "Cylindrical barrel.",
                )
            )
        for i in range(DOME_SECTIONS, -1, -1):
            theta = 90.0 * i / DOME_SECTIONS
            x, r = self.fwd_dome_point(theta)
            note = (
                "Forward dome tangent plane; forward skirt joint."
                if i == DOME_SECTIONS
                else (
                    "Forward dome apex; Instrument Unit interface."
                    if i == 0
                    else f"Forward dome at {theta:.2f} deg meridian angle."
                )
            )
            pts.append((x, r, note))
        return pts

    def meridian_deviation(self, pts: list[tuple[float, float, str]]) -> float:
        """Max distance between the C0 chord polyline and the true meridian."""
        worst = 0.0
        xy = [(x, r) for x, r, _ in pts]
        for (x0, r0), (x1, r1) in zip(xy, xy[1:]):
            if abs(r0 - r1) < 1e-9:  # barrel chord lies on the true surface
                continue
            for k in range(1, 20):
                s = k / 20.0
                xm, rm = x0 + s * (x1 - x0), r0 + s * (r1 - r0)
                if xm >= self.x_fwd_tangent:
                    t = math.atan2(rm / self.R, (xm - self.x_fwd_tangent) / self.h_dome)
                    xt, rt = self.fwd_dome_point(math.degrees(t))
                elif rm > self.a_ring or xm <= self.x_ring:
                    t = math.atan2(rm / self.R, (self.x_aft_tangent - xm) / self.h_dome)
                    xt, rt = self.aft_dome_point(math.degrees(t))
                else:
                    t = math.atan2(rm / self.a_ring, (xm - self.x_ring) / self.b_cap)
                    xt, rt = self.cap_point(math.degrees(t))
                worst = max(worst, math.hypot(xt - xm, rt - rm))
        return worst


def m(inches: float) -> float:
    return inches * IN2M


# =============================================================================
# XML CONSTRUCTION
# =============================================================================


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _num(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}f}"


def add_transformation(
    parent: ET.Element,
    *,
    rotation_y: float | None = None,
    translation_x: float | None = None,
    translation_z: float | None = None,
    scaling: float | None = None,
) -> None:
    tr = _sub(parent, "transformation")
    if scaling is not None:
        sc = _sub(tr, "scaling")
        _sub(sc, "y", _num(scaling))
        _sub(sc, "z", _num(scaling))
    if rotation_y is not None:
        rot = _sub(tr, "rotation")
        _sub(rot, "y", _num(rotation_y, 1))
    if translation_x is not None or translation_z is not None:
        tl = _sub(tr, "translation")
        if translation_x is not None:
            _sub(tl, "x", _num(translation_x))
        if translation_z is not None:
            _sub(tl, "z", _num(translation_z))


def add_fuel_tank(
    tanks: ET.Element,
    *,
    uid: str,
    name: str,
    description: str,
    origin_station: float,
) -> ET.Element:
    tank = _sub(tanks, "fuelTank")
    tank.set("uID", uid)
    _sub(tank, NAME_TAG, name)
    _sub(tank, "description", description)
    _sub(tank, "parentUID", PARENT_UID)
    add_transformation(
        tank, rotation_y=-90.0, translation_z=m(origin_station - PARENT_STATION)
    )
    return _sub(tank, "vessels")


def add_sectioned_vessel(
    vessels: ET.Element,
    *,
    uid: str,
    name: str,
    description: str,
    contour: list[tuple[float, float, str]],
    x_origin: float,
) -> None:
    vessel = _sub(vessels, "vessel")
    vessel.set("uID", uid)
    _sub(vessel, NAME_TAG, name)
    _sub(vessel, "description", description)
    add_transformation(vessel)

    sections = _sub(vessel, "sections")
    for i, (x, r, note) in enumerate(contour, start=1):
        sec = _sub(sections, "section")
        sec.set("uID", f"{uid}_sec{i}")
        _sub(sec, NAME_TAG, f"{name} Section {i}")
        _sub(sec, "description", f"{note} STA {x:.2f}.")
        add_transformation(sec, translation_x=m(x - x_origin))
        elements = _sub(sec, "elements")
        el = _sub(elements, "element")
        el.set("uID", f"{uid}_sec{i}_el1")
        _sub(el, NAME_TAG, f"{name} Section {i} Profile")
        _sub(el, "profileUID", PROFILE_UID)
        # circularProfile has unit diameter, so the scaling factor is the diameter.
        add_transformation(el, scaling=max(2.0 * m(r), 2.0 * APEX_RADIUS_M))

    segments = _sub(vessel, "segments")
    for i in range(1, len(contour)):
        seg = _sub(segments, "segment")
        seg.set("uID", f"{uid}_seg{i}")
        _sub(seg, NAME_TAG, f"{name} Segment {i}")
        _sub(seg, "fromElementUID", f"{uid}_sec{i}_el1")
        _sub(seg, "toElementUID", f"{uid}_sec{i + 1}_el1")


def build_lh2_tank(tanks: ET.Element, g: Geometry) -> None:
    contour = g.lh2_contour()
    origin = min(x for x, _, _ in contour)
    vessels = add_fuel_tank(
        tanks,
        uid=LH2_TANK_UID,
        name="S-IVB LH2 Fuel Tank",
        description=(
            "Propellant tank of the S-IVB third stage storing liquid hydrogen as fuel.\n"
            f"                            The LH2 compartment itself: barrel from STA {g.x_aft_tangent:.2f} to {g.x_fwd_tangent:.2f}, closed forward by an ellipsoidal dome of "
            f"{g.h_dome:.0f} in depth whose apex at STA {g.x_fwd_apex:.2f} coincides with the Instrument Unit interface [8].\n"
            f"                            Aft the compartment follows the aft dome inward from its tangent plane to the attach ring at STA {g.x_ring:.2f}, then turns back forward "
            f"along the common bulkhead to its apex at STA {g.x_cap_apex:.2f}, leaving the recess occupied by {LOX_TANK_UID}.\n"
            f"                            The aft closure is therefore re-entrant and the meridian has a {90.0 - g.theta_ring_deg:.2f} deg kink at the ring, so the vessel is "
            "described by sections and segments; no domeType can express it. The two tanks touch on the bulkhead and nowhere overlap."
        ),
        origin_station=origin,
    )
    add_sectioned_vessel(
        vessels,
        uid=LH2_VESSEL_UID,
        name="S-IVB LH2 Tank Vessel",
        description=(
            "Pressure vessel representing the liquid-hydrogen compartment of the S-IVB stage. "
            "Its aft closure is the common bulkhead, sampled at the same meridian angles as the "
            f"forward closure of {LOX_VESSEL_UID}, so the shared surface is generated identically."
        ),
        contour=contour,
        x_origin=origin,
    )


def build_lox_tank(tanks: ET.Element, g: Geometry) -> None:
    contour = g.lox_contour()
    origin = min(x for x, _, _ in contour)
    vessels = add_fuel_tank(
        tanks,
        uid=LOX_TANK_UID,
        name="S-IVB LOX Oxidizer Tank",
        description=(
            "Propellant tank of the S-IVB third stage storing liquid oxygen as oxidizer.\n"
            f"                            Lens formed by the aft dome of the propellant tank and the common bulkhead, welded together at one attach ring at STA {g.x_ring:.2f} "
            "and inserted into the barrel as a closed unit [8, Fig. 28].\n"
            f"                            The ring lies on the aft dome, so its radius {g.a_ring:.2f} in follows from its station; the station itself is solved from the documented "
            f"{V_LOX_DOC_FT3:.0f} cu ft [5]. The bulkhead is convex forward, of the same {DOME_HALF_AXIS_FRACTION:.4f} proportion, with its apex at STA {g.x_cap_apex:.2f}.\n"
            f"                            The two closures meet at a kink -- the aft dome arrives at {g.theta_ring_deg:.2f} deg meridian angle, the bulkhead leaves at 90 deg."
        ),
        origin_station=origin,
    )
    add_sectioned_vessel(
        vessels,
        uid=LOX_VESSEL_UID,
        name="S-IVB LOX Tank Vessel",
        description=(
            "Pressure vessel representing the liquid-oxygen tank volume of the S-IVB stage. "
            "Its aft closure is the aft dome of the propellant tank, which it shares as a "
            f"physical part with {LH2_VESSEL_UID}."
        ),
        contour=contour,
        x_origin=origin,
    )


# =============================================================================
# REPORTING
# =============================================================================


def report(g: Geometry, stream=sys.stderr) -> None:
    p = lambda s="": print(s, file=stream)  # noqa: E731
    lox, lh2 = g.lox_contour(), g.lh2_contour()
    p("S-IVB tank assembly -- stacked variant, no overlap")
    p("=" * 74)
    p(f"{'barrel radius (outer)':40s} {g.R:9.3f} in  {m(g.R):8.4f} m")
    p(
        f"{'end dome depth':40s} {g.h_dome:9.3f} in  "
        f"(ellipsoid ratio {DOME_HALF_AXIS_FRACTION:.4f})"
    )
    p()
    p(f"{'station':40s} {'[in]':>9s}  {'z rel. parent [m]':>18s}")
    p("-" * 74)
    for label, sta in [
        ("aft dome apex = LOX tank aft apex", g.x_aft_apex),
        ("LOX attach ring", g.x_ring),
        ("aft dome tangent / aft skirt joint", g.x_aft_tangent),
        ("common bulkhead apex", g.x_cap_apex),
        ("fwd dome tangent / fwd skirt joint", g.x_fwd_tangent),
        ("forward dome apex = IU interface", g.x_fwd_apex),
    ]:
        p(f"{label:40s} {sta:9.2f}  {m(sta - PARENT_STATION):18.4f}")
    p()
    p(f"{'attach ring radius':40s} {g.a_ring:9.3f} in  {m(g.a_ring):8.4f} m")
    p(f"{'bulkhead cap depth':40s} {g.b_cap:9.3f} in  {m(g.b_cap):8.4f} m")
    p(f"{'meridian kink at the ring':40s} {90.0 - g.theta_ring_deg:9.2f} deg")
    p()
    for label, contour in (("LOX", lox), ("LH2", lh2)):
        origin = min(x for x, _, _ in contour)
        p(f"{label} vessel (sections/segments)")
        p(f"{'  sections / segments':40s} {len(contour):9d} / {len(contour) - 1:d}")
        p(
            f"{'  origin station':40s} {origin:9.2f}     "
            f"z = {m(origin - PARENT_STATION):8.4f} m"
        )
        p(
            f"{'  C0 meridian deviation':40s} "
            f"{g.meridian_deviation(contour):9.3f} in  "
            f"{m(g.meridian_deviation(contour)) * 1000:8.2f} mm"
        )
    p()
    p("volume consistency (outer mould line against the documented volumes;")
    p("the two solids are disjoint, so these are directly comparable)")
    p("-" * 74)
    for label, geom_in3, doc_ft3 in [
        ("LOX", g.v_lox_geom(), V_LOX_DOC_FT3),
        ("LH2", g.v_lh2_geom(), V_LH2_DOC_FT3),
        ("total", g.v_envelope_geom(), V_LOX_DOC_FT3 + V_LH2_DOC_FT3),
    ]:
        geom_ft3 = geom_in3 / 1728.0
        dev = 100.0 * (geom_ft3 - doc_ft3) / doc_ft3
        p(
            f"{label:6s} model {geom_ft3:9.1f} cu ft   documented {doc_ft3:9.1f} cu ft"
            f"   {dev:+6.2f} %"
        )


# =============================================================================
# MAIN
# =============================================================================


def build_document(g: Geometry) -> ET.Element:
    tanks = ET.Element("fuelTanks")
    build_lh2_tank(tanks, g)
    build_lox_tank(tanks, g)
    return tanks


def serialise(tanks: ET.Element) -> str:
    ET.indent(tanks, space=INDENT, level=BASE_INDENT_LEVELS)
    prefix = INDENT * BASE_INDENT_LEVELS
    return (
        "\n".join(
            prefix + ET.tostring(child, encoding="unicode").strip() for child in tanks
        )
        + "\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--output", default="s-ivb_fuelTanks_stacked.xml")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    ap.add_argument(
        "--refs",
        action="store_true",
        help="print the reference entries for the saturnV.xml header",
    )
    args = ap.parse_args()

    if args.refs:
        print(NEW_REFERENCES)
        return

    g = Geometry()
    xml = serialise(build_document(g))
    report(g)

    if args.stdout:
        print(xml)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(xml)
        print(f"\nwrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
