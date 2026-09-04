#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate the CPACS ``<fuelTank>`` elements for the Saturn V S-IVB stage.

Run with::

    uv run generate_sivb_tanks.py                 # write ./s-ivb_fuelTanks.xml
    uv run generate_sivb_tanks.py --stdout        # print instead
    uv run generate_sivb_tanks.py --refs          # header reference entries


================================================================================
GEOMETRY MODEL
================================================================================

The S-IVB carries one welded propellant tank barrel that is internally divided by
a common bulkhead.  It is built from four separately manufactured shells --
forward dome, forward common bulkhead, aft common bulkhead, aft dome.  The
manufacturing sequence is explicit [8, Fig. 28]: the common bulkhead and the aft
dome are welded together at their attach rings *to form the LOX tank*, and the
LH2 barrel and forward dome are then assembled over it.  The model follows that
build order.

Two ``<fuelTank>`` elements are generated:

``s-ivb_lh2``  the complete welded propellant tank, from the aft dome apex to the
               forward dome apex.  Parametric vessel: cylinder plus two outward
               convex ellipsoidal domes.
``s-ivb_lox``  the lens-shaped oxidiser tank nested inside it, built from
               sections and segments.

Axial layout (Saturn V vehicle stations, inches)::

    STA 3222.56  ---.---            forward dome apex = IU interface
                    |  )
    STA 3100.56  ---+---            forward dome tangent = fwd skirt joint
                    |   |
                    |   |           barrel, 268.56 in
                    |   |
    STA 2889.82     |-.-|           LOX tank forward apex
    STA 2832.00  ---+(-)+---        aft dome tangent = aft skirt joint
                    |( )|
    STA 2779.63     |+-+|           LOX attach ring, r = 117.41 in
    STA 2710.04  ---'---            aft dome apex = LOX tank aft apex

DOME CONTOUR
------------

The end domes of the surrounding tank are ellipsoids of revolution with a radial
semi axis of 130 in and an axial semi axis of 122 in, i.e.
``halfAxisFraction = 0.9385``.  The 122 in is read off the inboard profile
[8, Fig. 25], where the forward dome fills the whole forward skirt: apex at the
IU interface, tangent at the skirt joint.  Three independent confirmations:

  - STA 3100.56 + 122 = 3222.56, exactly the forward skirt / IU interface already
    in saturnV.xml, so the dome apex closes flush with no protrusion;
  - the total documented volume pins the aft dome once the forward dome is known,
    because the bulkhead cancels out of the sum::

        pi R^2 * 268.56 + (2/3) pi R^2 * (h_fwd + h_aft) = 13,248 cu ft

    which gives h_aft = 121.93 in for h_fwd = 122 in;
  - with 122 in domes the barrel plus two domes encloses 13,249.5 cu ft against
    the documented 13,248 cu ft [5], i.e. +0.01 % on the outer mould line.

Hemispheres (h = R = 130 in) overshoot the LH2 volume by 3.2 %; the sqrt(2)
ellipsoid used on the S-IC and S-II is off by 10 %.  The one figure that does not
fit is the 44.0 ft quoted for the propellant tank in Figure 6-1 [5]; the model
gives 512.5 in = 42.7 ft.  Figure 6-1 is a schematic whose segment lengths
overlap and whose 7.0 ft aft skirt is already 1.5 in short of the 85.5 in station
value, so it is treated as the weaker source.

*Barrel length*, STA 2832.00 to 3100.56, is from the S-IVB station breakdown of
[3].  Independently confirmed on the Saturn IB stage, whose NASA stations
[8, Fig. 24] give 1540.859 - 1186.804 - 85.5 = 268.555 in between the aft skirt
and the forward skirt, and a 122.000 in forward skirt.  Both stages use the same
tank.

THE LOX TANK AND WHERE THE 117.41 in COME FROM
----------------------------------------------

The LOX tank is a lens made of two dissimilar domes meeting at one attach ring:

  - *aft dome*: not a separate part, but the aft dome of the surrounding tank
    itself, i.e. the 130 x 122 in ellipsoid with its apex at STA 2710.04.  The
    LOX tank is therefore flush with the outer mould line, as it must be -- the
    thrust structure is attached to this dome [6].
  - *forward dome (common bulkhead)*: an ellipsoid of the same 0.9385 proportion
    but sized to the ring, convex forward, bulging into the LH2 volume.

The ring radius is not a free choice.  The ring lies on the aft dome, so its
radius is fixed by its station::

    u = (2832.00 - x_ring) / 122
    a = 130 * sqrt(1 - u^2)

and the enclosed volume is then a function of the ring station alone::

    V = pi R^2 h * (2/3 - u + u^3/3)      segment of the aft dome below the ring
      + (2/3) pi a^2 * (0.9385 a)         the bulkhead cap above it

Setting that equal to the documented 2830 cu ft [5] gives x_ring = 2779.63 in,
hence u = 0.42926 and::

    a = 130 * sqrt(1 - 0.42926^2) = 130 * 0.90319 = 117.41 in

and a cap depth of 0.9385 * 117.41 = 110.19 in, apex at STA 2889.82.  So the
117.41 in is a derived quantity: one documented volume, one geometric
constraint, one unknown.  No consulted source dimensions the common bulkhead
directly, and [8, Fig. 25] is not accurate enough to scale off.

The two domes meet at the ring with a kink -- the aft dome arrives there at
64.58 deg meridian angle while the cap leaves at 90 deg -- which is why this
tank cannot use the parametric ``domeType`` branch: that branch mirrors one
meridian half about the mid-plane and can only produce two congruent, tangent
closures.

================================================================================
CPACS / TiGL NOTES
================================================================================

``CCPACSVessel::BuildVesselWireEllipsoid`` builds one half of the meridian and
``CCPACSVessel::BuildVesselWire`` mirrors it about the mid-plane of the cylinder.
A parametric vessel is therefore necessarily symmetric with two congruent,
outward convex domes.  The LH2 envelope satisfies that and uses the parametric
branch; the LOX tank does not and uses sections and segments.

A sectioned vessel is always lofted C0.  ``CCPACSVessel::BuildShapeFromSegments``
takes the continuity from the first segment, and ``CTiglAbstractSegment``
initialises ``_continuity`` to ``C0`` and never overwrites it, because the
``loftContinuity`` attribute exists on ``fuselageType``, ``wingType`` and
``ductType`` but not on ``vesselType`` -- even though a vessel reuses
``fuselageSectionsType`` and ``fuselageSegmentsType`` for its sections.  With
``smooth = false`` ``CTiglMakeLoft`` calls ``SetMaxDegree(1)``, so consecutive
profiles are joined by ruled surfaces.  Consequences:

  - the kink at the attach ring needs no special treatment; it comes for free;
  - but every dome is a cone frustum chain rather than a surface of revolution,
    and the meridian accuracy is set purely by ``LOX_DOME_SECTIONS``.  The
    console report prints the resulting maximum deviation from the true
    ellipse.

This is a schema gap in its own right: a sectioned vessel cannot be lofted
smoothly, whereas the geometrically identical fuselage can.

The two ``<fuelTank>`` solids overlap: ``s-ivb_lh2`` is the outer envelope and
encloses the LOX tank, so its geometric volume is that of the whole tank, not of
the LH2 compartment.  Any downstream capacity or mass evaluation has to subtract
the LOX vessel.

================================================================================
SOURCES
================================================================================

[1]..[4] are the references already defined in the saturnV.xml header; [3]
(Boeing, Saturn V Apollo Flight Configuration, Drawing Ref. 104573) is the source
of the S-IVB skirt stations reused here.  This script introduces [5]..[8], which
have to be appended to that header -- print them with ``--refs``.

[5] Saturn V Flight Manual, MSFC-MAN-503 / MSFC-MAN-507, Section VI, Figure 6-1
    "S-IVB Stage Structure": propellant tank 44.0 ft, forward skirt 10.2 ft, aft
    skirt 7.0 ft, thrust structure 5.2 ft, aft interstage 19 ft, stage diameter
    21.6 ft; LH2 tank 10,418 cu ft, LOX tank 2,830 cu ft.
[6] McCutcheon, K. D.: U.S. Manned Rocket Propulsion Evolution, Part 8.30, The
    Saturn S-IVB Stage: LH2 feed duct origin above the common bulkhead joint, PU
    probe lengths, thrust structure attached to the LOX aft dome, aft skirt
    bolted to the tank at its forward edge.
[7] heroicrelics.org, S-IVB (Saturn V) Overview: structural breakdown and
    manufacturing flow sequence.
[8] Osterhout, W. L. (dir.): Saturn S-IV / S-IVB Data Summary Handbook, Douglas
    Missile & Space Systems Division, 1 Oct 1965 (NASA N66-28064).  Fig. 24
    Saturn IB configuration (NASA stations, 260.00 in diameter), Fig. 25
    S-IVB/IB inboard profile (122 in forward dome, 85.500 in aft skirt), Fig. 27
    common bulkhead, Fig. 28 manufacturing plan, p. 54 S-IVB structures.
"""

from __future__ import annotations

import argparse
import math
import sys
from xml.etree import ElementTree as ET

# =============================================================================
# CONFIGURATION -- edit these when new evidence turns up
# =============================================================================

IN2M = 0.0254

# --- vehicle stations [in] ---------------------------------------------------
# Aft dome tangent plane == aft skirt / tank joint, forward dome tangent plane ==
# tank / forward skirt joint.  Both from the S-IVB station breakdown already used
# in saturnV.xml [3]; cross-checked against [8, Fig. 24] on the Saturn IB stage.
STA_AFT_TANGENT = 2832.00
STA_FWD_TANGENT = 3100.56

# Local origin of the parent component.  Both S-IVB skirts in saturnV.xml are
# children of s-ivb_aftInterstageAssembly (origin STA 2519).
PARENT_UID = "s-ivb_aftInterstageAssembly"
PARENT_STATION = 2519.00

# --- radius and dome contour -------------------------------------------------
# Outer mould line, 21 ft 8 in = 260 in diameter [5, 8], so that the barrel is
# flush with the adjacent skirts (6.604 m elsewhere in saturnV.xml).  The CPACS
# schema documents cylinderRadius/cylinderLength as *inner* dimensions.
CYLINDER_RADIUS_IN = 130.0

# Dome depth as a fraction of the radius: 122 in / 130 in [8, Fig. 25].
DOME_HALF_AXIS_FRACTION = 122.0 / 130.0

# --- LOX tank ----------------------------------------------------------------
# Station of the attach ring where the common bulkhead is welded to the aft dome.
# Solved from the documented LOX volume; see the module docstring.  Everything
# else about the LOX tank follows from this number.
LOX_RING_STATION = 2779.63

# Sections per dome, equally spaced in meridian angle.  The loft is C0 (ruled),
# so this alone sets the meridian accuracy; the report prints the deviation.
LOX_DOME_SECTIONS = 12

# Radius substituted for a mathematically zero apex radius, following the
# convention already used by s-ii_lh2_vessel in saturnV.xml.
APEX_RADIUS_M = 0.00001

# --- documented volumes [cu ft] ----------------------------------------------
# Figure 6-1 [5].
V_LOX_DOC_FT3 = 2830.0
V_LH2_DOC_FT3 = 10418.0

# --- naming ------------------------------------------------------------------
NAME_TAG = "name"
PROFILE_UID = "circularProfile"

LOX_TANK_UID = "s-ivb_oxidizer"
LOX_VESSEL_UID = "s-ivb_lox_vessel"
LH2_TANK_UID = "s-ivb_lh2"
LH2_VESSEL_UID = "s-ivb_lh2_vessel"

INDENT = "    "
BASE_INDENT_LEVELS = 5  # depth of <fuelTank> inside saturnV.xml

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

    def __init__(self, ring_station: float | None = None) -> None:
        self.R = CYLINDER_RADIUS_IN
        self.h_dome = self.R * DOME_HALF_AXIS_FRACTION

        self.x_aft_tangent = STA_AFT_TANGENT
        self.x_fwd_tangent = STA_FWD_TANGENT
        self.L_barrel = self.x_fwd_tangent - self.x_aft_tangent

        self.x_aft_apex = self.x_aft_tangent - self.h_dome
        self.x_fwd_apex = self.x_fwd_tangent + self.h_dome

        # --- LOX lens --------------------------------------------------------
        self.x_ring = LOX_RING_STATION if ring_station is None else ring_station
        u = (self.x_aft_tangent - self.x_ring) / self.h_dome
        if not 0.0 <= u <= 1.0:
            raise ValueError(
                "LOX_RING_STATION must lie between the aft dome apex and its "
                "tangent plane."
            )
        self.ring_u = u
        # The ring sits on the aft dome, so its radius follows from its station.
        self.a_ring = self.R * math.sqrt(max(0.0, 1.0 - u * u))
        self.b_cap = DOME_HALF_AXIS_FRACTION * self.a_ring
        self.x_cap_apex = self.x_ring + self.b_cap
        # Meridian angle at which the aft dome reaches the ring (90 deg = tangent
        # plane of the surrounding tank).  The cap leaves the ring at 90 deg, so
        # the difference is the kink angle.
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
        """LH2 compartment = envelope minus the nested LOX lens."""
        return self.v_envelope_geom() - self.v_lox_geom()

    # -- meridian ------------------------------------------------------------

    def aft_dome_point(self, theta_deg: float) -> tuple[float, float]:
        """Point on the aft dome of the surrounding tank.

        ``theta_deg`` runs from 0 at the apex to 90 at the tangent plane.
        """
        t = math.radians(theta_deg)
        return self.x_aft_tangent - self.h_dome * math.cos(t), self.R * math.sin(t)

    def cap_point(self, phi_deg: float) -> tuple[float, float]:
        """Point on the common bulkhead cap, 0 at the apex, 90 at the ring."""
        t = math.radians(phi_deg)
        return self.x_ring + self.b_cap * math.cos(t), self.a_ring * math.sin(t)

    def contour(self) -> list[tuple[float, float, str]]:
        """Sections from the aft apex over the attach ring to the cap apex."""
        n = LOX_DOME_SECTIONS
        pts: list[tuple[float, float, str]] = []
        for i in range(n + 1):
            theta = self.theta_ring_deg * i / n
            x, r = self.aft_dome_point(theta)
            note = (
                "Aft dome apex."
                if i == 0
                else (
                    "Attach ring: common bulkhead welded to the aft dome; "
                    "meridian kink."
                    if i == n
                    else f"Aft dome at {theta:.2f} deg meridian angle."
                )
            )
            pts.append((x, r, note))
        for i in range(n - 1, -1, -1):
            phi = 90.0 * i / n
            x, r = self.cap_point(phi)
            note = (
                "Common bulkhead apex."
                if i == 0
                else f"Common bulkhead at {phi:.2f} deg meridian angle."
            )
            pts.append((x, r, note))
        return pts

    def meridian_deviation(self) -> float:
        """Max distance between the C0 chord polyline and the true meridian."""
        worst = 0.0
        pts = [(x, r) for x, r, _ in self.contour()]
        for (x0, r0), (x1, r1) in zip(pts, pts[1:]):
            for k in range(1, 20):
                s = k / 20.0
                xm, rm = x0 + s * (x1 - x0), r0 + s * (r1 - r0)
                if xm <= self.x_ring:
                    # aft dome: x = xt - h cos t, r = R sin t
                    t = math.atan2(rm / self.R, (self.x_aft_tangent - xm) / self.h_dome)
                    xt, rt = self.aft_dome_point(math.degrees(t))
                else:
                    t = math.atan2(rm / self.a_ring, (xm - self.x_ring) / self.b_cap)
                    xt, rt = self.cap_point(math.degrees(t))
                worst = max(worst, math.hypot(xt - xm, rt - rm))
        return worst


def solve_ring_station(target_ft3: float = V_LOX_DOC_FT3) -> float:
    """Ring station whose lens reproduces ``target_ft3``."""
    lo, hi = (
        STA_AFT_TANGENT - CYLINDER_RADIUS_IN * DOME_HALF_AXIS_FRACTION,
        STA_AFT_TANGENT,
    )
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if Geometry(mid).v_lox_geom() / 1728.0 > target_ft3:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


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
    """Create a ``<fuelTank>`` whose local origin sits at ``origin_station``.

    ``rotation/y = -90`` maps the vessel's local +x -- the axis of revolution,
    which TiGL originates at the aft dome apex -- onto the vehicle +z, matching
    every other component in saturnV.xml.
    """
    tank = _sub(tanks, "fuelTank")
    tank.set("uID", uid)
    _sub(tank, NAME_TAG, name)
    _sub(tank, "description", description)
    _sub(tank, "parentUID", PARENT_UID)
    add_transformation(
        tank, rotation_y=-90.0, translation_z=m(origin_station - PARENT_STATION)
    )
    return _sub(tank, "vessels")


def build_lh2_tank(tanks: ET.Element, g: Geometry) -> None:
    vessels = add_fuel_tank(
        tanks,
        uid=LH2_TANK_UID,
        name="S-IVB LH2 Fuel Tank",
        description=(
            "Propellant tank of the S-IVB third stage storing liquid hydrogen as fuel.\n"
            f"                            Modelled as the complete welded propellant tank: barrel from STA {g.x_aft_tangent:.2f} to {g.x_fwd_tangent:.2f}, closed by two outward convex "
            f"ellipsoidal domes of {g.h_dome:.0f} in depth, apexes at STA {g.x_aft_apex:.2f} and {g.x_fwd_apex:.2f} [8].\n"
            f"                            The forward apex coincides with the forward skirt / Instrument Unit interface at STA {g.x_fwd_apex:.2f}; the dome fills the forward skirt exactly.\n"
            f"                            {LOX_TANK_UID} is nested inside this envelope and shares its aft dome, so this vessel encloses {g.v_envelope_geom() / 1728.0:.0f} cu ft rather "
            f"than the {V_LH2_DOC_FT3:.0f} cu ft of the LH2 compartment [5]; the compartment is the difference between the two."
        ),
        origin_station=g.x_aft_apex,
    )
    vessel = _sub(vessels, "vessel")
    vessel.set("uID", LH2_VESSEL_UID)
    _sub(vessel, NAME_TAG, "S-IVB LH2 Tank Vessel")
    _sub(
        vessel,
        "description",
        "Pressure vessel representing the welded propellant tank of the S-IVB stage. "
        f"It is the outer envelope; {LOX_VESSEL_UID} sits inside it.",
    )
    add_transformation(vessel)
    _sub(vessel, "cylinderRadius", _num(m(g.R)))
    _sub(vessel, "cylinderLength", _num(m(g.L_barrel)))
    dome = _sub(vessel, "domeType")
    ell = _sub(dome, "ellipsoid")
    _sub(ell, "halfAxisFraction", _num(DOME_HALF_AXIS_FRACTION, 4))


def build_lox_tank(tanks: ET.Element, g: Geometry) -> None:
    vessels = add_fuel_tank(
        tanks,
        uid=LOX_TANK_UID,
        name="S-IVB LOX Oxidizer Tank",
        description=(
            "Propellant tank of the S-IVB third stage storing liquid oxygen as oxidizer.\n"
            f"                            Lens formed by the aft dome of the surrounding tank and the common bulkhead, welded together at one attach ring at STA {g.x_ring:.2f} "
            "and inserted into the barrel as a closed unit [8, Fig. 28].\n"
            f"                            The ring lies on the aft dome, so its radius {g.a_ring:.2f} in follows from its station; the station itself is solved from the documented "
            f"{V_LOX_DOC_FT3:.0f} cu ft [5]. The bulkhead is convex forward, of the same {DOME_HALF_AXIS_FRACTION:.4f} proportion, with its apex at STA {g.x_cap_apex:.2f}.\n"
            f"                            The two closures meet at a kink -- the aft dome arrives at {g.theta_ring_deg:.2f} deg meridian angle, the bulkhead leaves at 90 deg -- "
            "so the vessel is described by sections and segments; no domeType can express two dissimilar closures."
        ),
        origin_station=g.x_aft_apex,
    )
    vessel = _sub(vessels, "vessel")
    vessel.set("uID", LOX_VESSEL_UID)
    _sub(vessel, NAME_TAG, "S-IVB LOX Tank Vessel")
    _sub(
        vessel,
        "description",
        "Pressure vessel representing the liquid-oxygen tank volume of the S-IVB stage. "
        "Its aft closure is geometrically identical to the aft dome of "
        f"{LH2_VESSEL_UID}, which it shares as a physical part.",
    )
    add_transformation(vessel)

    contour = g.contour()
    sections = _sub(vessel, "sections")
    for i, (x, r, note) in enumerate(contour, start=1):
        sec = _sub(sections, "section")
        sec.set("uID", f"{LOX_VESSEL_UID}_sec{i}")
        _sub(sec, NAME_TAG, f"S-IVB LOX Tank Vessel Section {i}")
        _sub(sec, "description", f"{note} STA {x:.2f}.")
        add_transformation(sec, translation_x=m(x - g.x_aft_apex))
        elements = _sub(sec, "elements")
        el = _sub(elements, "element")
        el.set("uID", f"{LOX_VESSEL_UID}_sec{i}_el1")
        _sub(el, NAME_TAG, f"S-IVB LOX Tank Vessel Section {i} Profile")
        _sub(el, "profileUID", PROFILE_UID)
        # circularProfile has unit diameter, so the scaling factor is the diameter.
        add_transformation(el, scaling=max(2.0 * m(r), 2.0 * APEX_RADIUS_M))

    segments = _sub(vessel, "segments")
    for i in range(1, len(contour)):
        seg = _sub(segments, "segment")
        seg.set("uID", f"{LOX_VESSEL_UID}_seg{i}")
        _sub(seg, NAME_TAG, f"S-IVB LOX Tank Vessel Segment {i}")
        _sub(seg, "fromElementUID", f"{LOX_VESSEL_UID}_sec{i}_el1")
        _sub(seg, "toElementUID", f"{LOX_VESSEL_UID}_sec{i + 1}_el1")


# =============================================================================
# REPORTING
# =============================================================================


def report(g: Geometry, stream=sys.stderr) -> None:
    p = lambda s="": print(s, file=stream)  # noqa: E731
    p("S-IVB tank assembly -- resolved geometry")
    p("=" * 74)
    p(f"{'barrel radius (outer)':40s} {g.R:9.3f} in  {m(g.R):8.4f} m")
    p(
        f"{'end dome depth':40s} {g.h_dome:9.3f} in  "
        f"(halfAxisFraction {DOME_HALF_AXIS_FRACTION:.4f})"
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
    p("LOX vessel (sections/segments)")
    p(f"{'  attach ring radius':40s} {g.a_ring:9.3f} in  {m(g.a_ring):8.4f} m")
    p(f"{'  bulkhead cap depth':40s} {g.b_cap:9.3f} in  {m(g.b_cap):8.4f} m")
    p(
        f"{'  aft dome meridian angle at ring':40s} {g.theta_ring_deg:9.2f} deg"
        f"   kink {90.0 - g.theta_ring_deg:.2f} deg"
    )
    p(
        f"{'  sections / segments':40s} {2 * LOX_DOME_SECTIONS + 1:9d} / "
        f"{2 * LOX_DOME_SECTIONS:d}"
    )
    p(
        f"{'  C0 meridian deviation':40s} {g.meridian_deviation():9.3f} in  "
        f"{m(g.meridian_deviation()) * 1000:8.2f} mm"
    )
    p()
    p("LH2 vessel (parametric, full welded tank envelope)")
    p(f"{'  cylinderRadius':40s} {g.R:9.3f} in  {m(g.R):8.4f} m")
    p(f"{'  cylinderLength':40s} {g.L_barrel:9.3f} in  {m(g.L_barrel):8.4f} m")
    p(
        f"{'  origin station':40s} {g.x_aft_apex:9.2f}     "
        f"z = {m(g.x_aft_apex - PARENT_STATION):8.4f} m"
    )
    p()
    p("volume consistency (outer mould line against the documented volumes)")
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
    p()
    p(
        f"ring station reproducing {V_LOX_DOC_FT3:.0f} cu ft exactly: "
        f"STA {solve_ring_station():.3f}  (configured: {g.x_ring:.3f})"
    )


# =============================================================================
# MAIN
# =============================================================================


def build_document(g: Geometry) -> ET.Element:
    tanks = ET.Element("fuelTanks")
    # Ascending UID order, matching the convention used in saturnV.xml.
    build_lh2_tank(tanks, g)
    build_lox_tank(tanks, g)
    return tanks


def serialise(tanks: ET.Element) -> str:
    # ElementTree only indents *inside* an element, so the leading indent of each
    # top level child is prepended by hand.
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
    ap.add_argument("-o", "--output", default="s-ivb_fuelTanks.xml")
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
