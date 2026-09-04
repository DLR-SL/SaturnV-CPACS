# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "scipy>=1.11"]
# ///
"""
generate_s_ii_tanks.py
======================

Generates the CPACS ``<fuelTank>`` nodes for the Saturn V S-II second stage:

  * ``s-ii_lox``  -- the liquid-oxygen tank, described PARAMETRICALLY
                    (cylinderRadius / cylinderLength / domeType/ellipsoid).
  * ``s-ii_lh2``  -- the liquid-hydrogen tank, described EXPLICITLY
                    (sections / segments).

Run with uv::

    uv run generate_s_ii_tanks.py            # writes s-ii_tanks.xml
    uv run generate_s_ii_tanks.py -          # writes to stdout

All modelling assumptions are set as module-level constants in the
ASSUMPTIONS block below and are documented there.  Nothing is taken from
the command line, so the file itself is the complete record of how the
geometry was produced.


WHY THE TWO TANKS ARE MODELLED DIFFERENTLY
------------------------------------------
The S-II LOX tank consists of two ellipsoidal half-shells joined at a short
cylindrical bolting ring [9].  Both of its domes are convex outwards, so it
maps cleanly onto the parametric ``domeType/ellipsoid`` branch of CPACS.

The LH2 tank does not:

  (a) Its aft closure is the common bulkhead shared with the LOX tank and is
      convex forward, i.e. re-entrant into the LH2 volume [9].  All CPACS
      domeType variants generate outward-convex domes at both ends, and CPACS
      offers no way of declaring a wall shared between two vessels.
  (b) Its forward bulkhead carries the "modified ellipsoidal" compound contour
      documented for the S-II gores [4], which no single domeType reproduces.

Consequence for this script: the LH2 tank's aft sections are sampled from
EXACTLY the same ellipse that the LOX tank's forward dome is generated from,
so that the two lofts share a coincident surface.  If ``LOX_HALF_AXIS_FRACTION``
or ``TANK_RADIUS`` is changed, both tanks follow automatically.


MERIDIAN CONSTRUCTION OF THE LH2 FORWARD BULKHEAD
-------------------------------------------------
Let ``t`` be the axial distance from the bulkhead equator towards the apex,
``r`` the local radius, and ``phi`` the angle between the meridian tangent and
the vessel axis (phi = 0 at the equator, phi = 90 deg at the apex).  Four
tangent-continuous pieces of revolution, from the equator to the apex:

  1. Toroidal knuckle, radius ``r_k``, spanning phi = 0 .. KNUCKLE_ANGLE_DEG,
     tangent to the cylindrical barrel at phi = 0.  Its radius is set to
     r_k = h^2 / R, the meridional radius of curvature of the nominal ellipse
     of equal height at its equator.
  2. Elliptical crown with radial semi-axis ``a``, axial semi-axis ``b`` and
     centre offset ``t_c``, joined tangentially to the knuckle.
  3. Conical band of constant slope, tangent to the elliptical crown at its
     outer end, running inwards from r = CONE_START_FACTOR * r_dollar to
     r = r_dollar.
  4. Spherical dollar cap of radius rho = r_dollar / cos(phi_2), tangent to the
     cone, closing the meridian on the axis.

The unknowns a, b, t_c follow from the closed system

    r_E(phi_1) = r_T(phi_1)                       position continuity
    t_E(phi_1) = t_T(phi_1)                       (slope continuity is implicit
                                                   in the shared parameter phi)
    t_cone_end + rho * (1 - sin(phi_2)) = h        meridian reaches the axis
                                                   at the documented depth h

solved numerically with scipy.optimize.fsolve.  ``phi_2`` is found per
iteration from r_E(phi_2) = CONE_START_FACTOR * r_dollar.


REFERENCES
----------
Numbering follows the primary source list in the header of saturnV.xml.  [4] is
already defined there; [5] is the Saturn V Flight Manual, cited there for the
S-IVB but used here for the S-II stations as well; [9] is introduced by this
script and has to be appended to that list.

[4] Cerquettini, C. T.: The Common Bulkhead for the Saturn S-II Vehicle.
    North American Aviation, Inc., Space and Information Systems Division,
    Downey, CA.  Scan: heroicrelics.org,
    http://heroicrelics.org/info/s-ii/common-bulkhead-for-s-ii.html
    -- gores carry "a compound contour, including three curves -- toroidal,
       elliptical and conical"; central "dollar" cap 3 ft in diameter;
       dome shells "33 feet in diameter and 12 feet high".
[5] Saturn V Flight Manual, SA-503 / SA-507. MSFC-MAN-503 (1 Nov 1968) /
    MSFC-MAN-507 (15 Aug 1969), Marshall Space Flight Center, Huntsville, AL.
    -- Section IV: S-II stage structure, tank diameter 396 in, S-II theoretical
       datum STA 1541, LOX tank equator STA 1848.
[9] McCutcheon, K. D.: U.S. Manned Rocket Propulsion Evolution, Part 8.20:
    The Saturn V S-II Stage. Aircraft Engine Historical Society, 2021/2024.
    https://www.enginehistory.org/Rockets/RPE08.20/RPE08.20.shtml
    -- "The LH2 tank was a long cylinder with a concave modified ellipsoidal
       bulkhead forward and a convex modified ellipsoidal bulkhead aft. The aft
       bulkhead was common to the LOX tank."
    -- "The LOX tank consisted of ellipsoidal fore and aft halves."
    -- bolting ring 15 in long, attaching LOX tank, aft skirt and LH2 cylinder.

Entry to append to the saturnV.xml header (matching the style used there)::

        [9] McCutcheon, K.D. U.S. Manned Rocket Propulsion Evolution, Part 8.20:
            The Saturn V S-II Stage. Aircraft Engine Historical Society,
            rev. 2024.
            https://www.enginehistory.org/Rockets/RPE08.20/RPE08.20.shtml
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq, fsolve

# =============================================================================
# ASSUMPTIONS
# =============================================================================
# Every value below is either sourced (marked [n]) or an explicit modelling
# choice (marked CHOICE).  Changing any of them regenerates a consistent pair
# of tanks.

IN = 0.0254  # inch -> metre

# --- Geometry, sourced ---------------------------------------------------
TANK_DIAMETER = 396.0 * IN  # 10.0584 m, S-II tank outer diameter [5][9]
DOLLAR_DIAMETER = 36.0 * IN  # 0.9144 m, central "dollar" cap [4]
BOLTING_RING_LENGTH = 15.0 * IN  # 0.3810 m, LOX tank equator ring [9]

# Bulkhead depths, measured from the Y-ring / bolting-ring tangent plane to the
# apex.  Taken from the existing station-based stack-up of the dataset and NOT
# changed here.  The only primary dimension found for the dome shells is
# "33 feet in diameter and 12 feet high" [4], i.e. 144 in, which brackets these
# values together with the 140 in implied by a root-2 ellipsoid.
COMMON_BULKHEAD_DEPTH = 3.256  # m (128.19 in) -- LOX fwd dome = LH2 aft dome
FORWARD_BULKHEAD_DEPTH = 3.512  # m (138.27 in) -- LH2 forward dome
LH2_CYLINDER_LENGTH = 13.555  # m (533.66 in) -- LH2 barrel, equator to Y-ring

# --- Station bookkeeping, sourced where marked ---------------------------
# Vehicle stations in inches, MSFC convention (STA 100 = engine gimbal plane,
# increasing forward).  The S-II theoretical datum is STA 1541 [5]; the LOX
# tank equator sits at STA 1848 [5][9].  The local x = 0 of both fuelTank nodes
# is placed at the LOX tank equator, i.e. at the FORWARD end of the bolting
# ring, which is also where the LH2 cylinder begins.
STA_LOX_EQUATOR = 1848.0  # [5][9]
STA_S2_DATUM = 1541.0  # [5]

# CHOICE: the 15 in bolting ring is placed entirely AFT of STA 1848, so the
# LOX tank cylinder spans STA 1833 .. 1848.  No source states on which side of
# STA 1848 the ring sits; the alternative (ring centred on STA 1848) shifts the
# LOX tank aft dome by 7.5 in.
BOLTING_RING_AFT_OF_EQUATOR = True

# --- Compound meridian of the LH2 forward bulkhead -----------------------
# CHOICE: extent of the toroidal knuckle.  No source gives dish, knuckle or
# cone dimensions for the S-II bulkheads.
KNUCKLE_ANGLE_DEG = 20.0
# CHOICE: the conical band starts where the meridian radius has fallen to this
# multiple of the dollar radius, i.e. its width equals one dollar radius.
CONE_START_FACTOR = 2.0
# CHOICE: ordering of the three gore curves.  Reference [4] names them
# ("toroidal, elliptical and conical") without stating a sequence; the ordering
# used here is the only one that yields a tangent-continuous, closed dome
# ending in the documented central dollar cap.

# --- Discretisation, CHOICE ----------------------------------------------
# Meridian angles [deg] at which the knuckle and the elliptical crown are
# sampled.  The three piece boundaries (knuckle/ellipse, ellipse/cone,
# cone/cap) and the apex are always emitted in addition, so that curvature
# discontinuities coincide with segment ends rather than falling inside a loft
# span.
FWD_KNUCKLE_SAMPLE_DEG = (0.0, 10.0, 20.0)
FWD_ELLIPSE_SAMPLE_DEG = (30.0, 40.0, 50.0, 60.0, 70.0, 75.0, 80.0)
# Sampling of the aft (common) bulkhead, a pure ellipse identical to the LOX
# tank's forward dome.  Same meridian-angle convention.
AFT_SAMPLE_DEG = (0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 85.0)
# Extra stations along the barrel, as offsets [m] from the LH2 equator, used to
# keep the loft straight between the two bulkheads.
BARREL_EXTRA_STATIONS = (0.1, 1.0, 3.0)

# --- CPACS bookkeeping ---------------------------------------------------
PROFILE_UID = "circularProfile"  # unit-diameter circle -> scaling = diameter
APEX_DIAMETER = 1.0e-5  # degenerate section stand-in at the apex
LH2_PARENT_UID = "s-ii_interstage"
LOX_PARENT_UID = "s-ii_interstage"
LH2_TANK_Z = 7.7983  # m, translation of the LH2 fuelTank node
BASE_INDENT = 20  # spaces before <fuelTank>, matches saturnV.xml

# =============================================================================
# Derived constants
# =============================================================================
R = TANK_DIAMETER / 2.0
R_DOLLAR = DOLLAR_DIAMETER / 2.0
R_CONE_START = CONE_START_FACTOR * R_DOLLAR
# The LOX tank's forward dome IS the common bulkhead, so the two tanks share
# this single number:
LOX_HALF_AXIS_FRACTION = COMMON_BULKHEAD_DEPTH / R

# Overall length of the parametric LOX vessel: two domes plus the bolting ring.
LOX_VESSEL_LENGTH = 2.0 * COMMON_BULKHEAD_DEPTH + BOLTING_RING_LENGTH

# Where TiGL places the local origin of a parametric vessel is not stated in
# the schema.  Verified against a TiGL rendering of this dataset: the origin
# sits at the AFT DOME APEX, and the vessel extends from there in +x.  The
# earlier assumption (origin at the aft end of the cylindrical section) placed
# the LOX tank 3.637 m too far forward.
# Permitted values: "aft_dome_apex", "cylinder_aft_end", "cylinder_centre".
LOX_VESSEL_ORIGIN = "aft_dome_apex"

# Position of the LOX vessel's local x = 0 relative to the LH2 fuelTank origin
# (which sits at the LOX tank equator, STA 1848).  The constraint is that the
# LOX tank's FORWARD dome apex must coincide with the LH2 tank's aft bulkhead
# apex at local x = COMMON_BULKHEAD_DEPTH, so that the common bulkhead is a
# single coincident surface.
_RING_AFT = (
    BOLTING_RING_LENGTH if BOLTING_RING_AFT_OF_EQUATOR else BOLTING_RING_LENGTH / 2.0
)
_LOX_ORIGIN_OFFSET = {
    # forward apex is LOX_VESSEL_LENGTH ahead of the aft apex
    "aft_dome_apex": COMMON_BULKHEAD_DEPTH - LOX_VESSEL_LENGTH,
    # forward apex is (cylinder + forward dome) ahead of the cylinder aft end
    "cylinder_aft_end": -_RING_AFT,
    # forward apex is (cylinder/2 + forward dome) ahead of the cylinder centre
    "cylinder_centre": -_RING_AFT + BOLTING_RING_LENGTH / 2.0,
}[LOX_VESSEL_ORIGIN]
LOX_TANK_Z = LH2_TANK_Z + _LOX_ORIGIN_OFFSET


# =============================================================================
# Meridian mathematics
# =============================================================================
@dataclass
class CompoundDome:
    """Solved parameters of a toroidal/elliptical/conical/spherical meridian."""

    h: float  # dome depth, equator -> apex [m]
    r_k: float  # knuckle radius [m]
    phi_1: float  # knuckle/ellipse joint, meridian angle [rad]
    phi_2: float  # ellipse/cone joint, meridian angle [rad]
    a: float  # ellipse radial semi-axis [m]
    b: float  # ellipse axial semi-axis [m]
    t_c: float  # ellipse centre offset along the axis [m]
    t_1: float
    r_1: float  # knuckle/ellipse joint
    t_2: float
    r_2: float  # ellipse/cone joint
    t_3: float  # cone/cap joint (r = R_DOLLAR there)
    rho: float  # dollar-cap radius [m]
    residual: float


def _ellipse_point(a: float, b: float, t_c: float, phi: float) -> tuple[float, float]:
    """Point (t, r) on an ellipse of semi-axes a (radial) and b (axial) whose
    meridian tangent makes the angle ``phi`` with the vessel axis."""
    alpha = np.arctan((b / a) * np.tan(phi))
    return t_c + b * np.sin(alpha), a * np.cos(alpha)


def _torus_point(r_k: float, phi: float) -> tuple[float, float]:
    """Point (t, r) on a knuckle of radius ``r_k`` tangent to the barrel."""
    return r_k * np.sin(phi), R - r_k * (1.0 - np.cos(phi))


def solve_compound_dome(h: float) -> CompoundDome:
    """Solve the meridian equation system for a dome of depth ``h``."""
    r_k = h**2 / R  # equator curvature of the nominal ellipse
    phi_1 = np.radians(KNUCKLE_ANGLE_DEG)
    t_1, r_1 = _torus_point(r_k, phi_1)

    def chain(x):
        a, b, t_c = x
        phi_2 = brentq(
            lambda f: _ellipse_point(a, b, t_c, f)[1] - R_CONE_START,
            np.radians(45.0),
            np.radians(89.99),
        )
        t_2, r_2 = _ellipse_point(a, b, t_c, phi_2)
        t_3 = t_2 + (R_CONE_START - R_DOLLAR) / np.tan(phi_2)
        rho = R_DOLLAR / np.cos(phi_2)
        return phi_2, t_2, r_2, t_3, rho, t_3 + rho * (1.0 - np.sin(phi_2))

    def equations(x):
        a, b, t_c = x
        t_e, r_e = _ellipse_point(a, b, t_c, phi_1)
        return [r_e - r_1, t_e - t_1, chain(x)[5] - h]

    a, b, t_c = fsolve(equations, [R, h, 0.0])
    phi_2, t_2, r_2, t_3, rho, _ = chain([a, b, t_c])
    return CompoundDome(
        h=h,
        r_k=r_k,
        phi_1=phi_1,
        phi_2=phi_2,
        a=a,
        b=b,
        t_c=t_c,
        t_1=t_1,
        r_1=r_1,
        t_2=t_2,
        r_2=r_2,
        t_3=t_3,
        rho=rho,
        residual=float(np.max(np.abs(equations([a, b, t_c])))),
    )


def compound_meridian(dome: CompoundDome) -> list[tuple[float, float, str]]:
    """Sample a solved compound dome from the equator (t = 0) to the apex."""
    pts: list[tuple[float, float, str]] = []
    for deg in FWD_KNUCKLE_SAMPLE_DEG:
        phi = np.radians(deg)
        t, r = _torus_point(dome.r_k, phi)
        label = (
            "equator, start of the toroidal knuckle, tangent to the cylindrical barrel"
            if deg == 0.0
            else f"toroidal knuckle at {deg:g} deg meridian angle"
        )
        pts.append((t, r, label))
    for deg in FWD_ELLIPSE_SAMPLE_DEG:
        phi = np.radians(deg)
        t, r = _ellipse_point(dome.a, dome.b, dome.t_c, phi)
        if r <= R_CONE_START:
            continue  # already inside the conical band
        pts.append((t, r, f"elliptical crown at {deg:g} deg meridian angle"))
    pts.append(
        (dome.t_2, dome.r_2, "joint between the elliptical crown and the conical band")
    )
    pts.append(
        (
            dome.t_3,
            R_DOLLAR,
            "joint between the conical band and the spherical dollar cap",
        )
    )
    pts.append((dome.h, 0.0, "apex, closing point of the spherical dollar cap"))
    return pts


def ellipsoid_meridian(h: float) -> list[tuple[float, float, str]]:
    """Sample a pure ellipsoidal dome of depth ``h`` from the equator to the
    apex, using the same meridian-angle parametrisation.  This reproduces the
    contour that CPACS generates for domeType/ellipsoid with
    halfAxisFraction = h / R, so the LH2 aft sections lie exactly on the LOX
    tank's forward dome."""
    pts = []
    for deg in AFT_SAMPLE_DEG:
        phi = np.radians(deg)
        t, r = _ellipse_point(R, h, 0.0, phi)
        label = (
            "equator, tangent to the cylindrical barrel; coincident with the "
            "LOX tank bolting ring"
            if deg == 0.0
            else f"ellipsoidal common bulkhead at {deg:g} deg meridian angle"
        )
        pts.append((t, r, label))
    pts.append((h, 0.0, "apex of the common bulkhead, protruding into the LH2 volume"))
    return pts


# =============================================================================
# XML emission
# =============================================================================
def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _block(text: str, indent: int) -> str:
    """Re-indent a multi-line description body."""
    pad = " " * indent
    lines = [ln.strip() for ln in text.strip().splitlines()]
    return ("\n" + pad).join(_esc(ln) for ln in lines)


def emit_sections(
    stations, uid_base: str, name_base: str, indent: int
) -> tuple[str, str]:
    pad = " " * indent
    secs, segs = [], []
    for i, (x, dia, desc) in enumerate(stations, start=1):
        secs.append(
            f'{pad}<section uID="{uid_base}_sec{i}">\n'
            f"{pad}    <name>{name_base} Section {i}</name>\n"
            f"{pad}    <description>{_esc(desc)}</description>\n"
            f"{pad}    <transformation>\n"
            f"{pad}        <translation>\n"
            f"{pad}            <x>{x:.6f}</x>\n"
            f"{pad}        </translation>\n"
            f"{pad}    </transformation>\n"
            f"{pad}    <elements>\n"
            f'{pad}        <element uID="{uid_base}_sec{i}_el1">\n'
            f"{pad}            <name>{name_base} Section {i} Profile</name>\n"
            f"{pad}            <profileUID>{PROFILE_UID}</profileUID>\n"
            f"{pad}            <transformation>\n"
            f"{pad}                <scaling>\n"
            f"{pad}                    <y>{dia:.6f}</y>\n"
            f"{pad}                    <z>{dia:.6f}</z>\n"
            f"{pad}                </scaling>\n"
            f"{pad}            </transformation>\n"
            f"{pad}        </element>\n"
            f"{pad}    </elements>\n"
            f"{pad}</section>"
        )
        if i > 1:
            segs.append(
                f'{pad}<segment uID="{uid_base}_seg{i - 1}">\n'
                f"{pad}    <name>{name_base} Segment {i - 1}</name>\n"
                f"{pad}    <fromElementUID>{uid_base}_sec{i - 1}_el1</fromElementUID>\n"
                f"{pad}    <toElementUID>{uid_base}_sec{i}_el1</toElementUID>\n"
                f"{pad}</segment>"
            )
    return "\n".join(secs), "\n".join(segs)


def build_lh2_stations(aft: list, fwd: list) -> list[tuple[float, float, str]]:
    """Assemble the ordered station list of the LH2 vessel, aft apex first."""
    st: list[tuple[float, float, str]] = []
    for t, r, label in reversed(aft):
        st.append((t, 2 * r, f"Aft (common) bulkhead: {label}."))
    for dx in BARREL_EXTRA_STATIONS:
        st.append((dx, TANK_DIAMETER, "Cylindrical barrel."))
    st.append(
        (
            LH2_CYLINDER_LENGTH,
            TANK_DIAMETER,
            "Cylindrical barrel, forward end; equator of the forward bulkhead and "
            "start of its toroidal knuckle, tangent to the barrel.",
        )
    )
    for t, r, label in fwd[1:]:
        st.append((LH2_CYLINDER_LENGTH + t, 2 * r, f"Forward bulkhead: {label}."))
    # Degenerate end sections
    st[0] = (st[0][0], APEX_DIAMETER, st[0][2])
    st[-1] = (st[-1][0], APEX_DIAMETER, st[-1][2])
    return st


LH2_TANK_DESC = """Propellant tank of the S-II second stage storing liquid hydrogen as fuel.
The cylindrical section begins at the LOX tank equator, STA {sta_eq:.0f} ({above:.0f} in above the theoretical datum at STA {sta_datum:.0f}) [2,3]; the barrel is closed forward by an ellipsoidal bulkhead and aft by the common bulkhead shared with the S-II LOX tank [3,4].
Both bulkheads are described in the primary sources as "modified ellipsoidal" and are convex in the forward direction, i.e. the forward bulkhead bulges out of the tank while the common bulkhead protrudes back into the LH2 volume [9].
Tank diameter {dia:.0f} in ({dia_m:.4f} m); forward bulkhead depth {fwd:.2f} in, common bulkhead depth {aft:.2f} in, both measured from the respective Y-ring / bolting-ring tangent plane to the apex.
Generated by generate_s_ii_tanks.py."""

LH2_VESSEL_DESC = """Pressure vessel representing the liquid-hydrogen tank volume of the S-II stage.
The vessel is described by explicit sections and segments rather than by the parametric domeType branch, because the aft closure is a common bulkhead shared with the S-II LOX tank and is convex forward, i.e. re-entrant into the LH2 volume, and because the forward bulkhead carries the "modified ellipsoidal" compound contour documented for the S-II gores [4], which no single domeType reproduces.
Aft closure: a pure ellipsoid of depth {aft:.4f} m, sampled from exactly the contour that the s-ii_lox vessel generates from domeType/ellipsoid with halfAxisFraction = {haf:.6f}, so that the two tanks share a coincident surface.
Forward closure: four tangent-continuous pieces of revolution, in this order from the equator to the apex, a toroidal knuckle tangent to the cylindrical barrel, an elliptical crown, a conical band, and a spherical cap closing the central circular "dollar" plate. Sections are placed on the three piece boundaries so that the curvature discontinuities coincide with segment ends; the remaining sections sample the knuckle and the crown at fixed meridian angles.
The ordering of the three gore curves is an interpretation of [4], which names them without giving a sequence; the knuckle extent and the width of the conical band are modelling choices, as no source gives dish, knuckle or cone dimensions for the S-II bulkheads. The bulkhead depths are taken from the station-based stack-up.
Relative to a pure ellipsoid of equal height the forward bulkhead encloses {dvol:+.1f} % volume and its meridian deviates by at most {ddev:.0f} mm."""

LOX_TANK_DESC = """Propellant tank of the S-II second stage storing liquid oxygen as oxidizer.
The tank consists of ellipsoidal fore and aft halves joined at a {ring:.0f} in bolting ring, which also carries the attachment of the aft skirt and of the LH2 cylinder [9]; it therefore has no barrel of its own beyond that ring.
The forward half is the common bulkhead shared with the s-ii_lh2 tank and protrudes forward into the LH2 volume [9].
Tank diameter {dia:.0f} in ({dia_m:.4f} m); dome depth {aft:.2f} in, i.e. halfAxisFraction = {haf:.6f}.
Generated by generate_s_ii_tanks.py."""

LOX_VESSEL_DESC = """Pressure vessel representing the liquid-oxygen tank volume of the S-II stage.
Both closures are convex outwards, so unlike the LH2 tank this vessel maps onto the parametric domeType branch and is described by cylinderRadius, cylinderLength and domeType/ellipsoid.
The sources describe the bulkheads as "modified ellipsoidal" [9] and the gores as carrying a toroidal/elliptical/conical compound contour [4]; the pure ellipsoid used here is therefore an approximation, chosen so that the tank stays parametric. The aft sections of the s-ii_lh2 vessel are sampled from this same ellipsoid so that the common bulkhead is a single coincident surface.
cylinderLength is the {ring:.0f} in bolting ring [9]. The bolting ring is placed entirely aft of the LOX tank equator at STA {sta_eq:.0f}; no source states on which side of that station it sits."""


def main() -> None:
    dest = sys.argv[1] if len(sys.argv) > 1 else "s-ii_tanks.xml"

    fwd_dome = solve_compound_dome(FORWARD_BULKHEAD_DEPTH)
    fwd_pts = compound_meridian(fwd_dome)
    aft_pts = ellipsoid_meridian(COMMON_BULKHEAD_DEPTH)
    stations = build_lh2_stations(aft_pts, fwd_pts)

    # Quality metrics quoted in the vessel description
    t = np.array([p[0] for p in fwd_pts])
    r = np.array([p[1] for p in fwd_pts])
    v_compound = float(np.trapezoid(np.pi * r**2, t))
    v_ellipsoid = 2.0 / 3.0 * np.pi * R**2 * FORWARD_BULKHEAD_DEPTH
    d_vol = 100.0 * (v_compound - v_ellipsoid) / v_ellipsoid
    theta = np.linspace(0.0, np.pi / 2.0, 4000)
    et = FORWARD_BULKHEAD_DEPTH * np.sin(theta)
    er = R * np.cos(theta)
    d_dev = 1000.0 * max(
        float(np.min(np.hypot(tt - et, rr - er))) for tt, rr, _ in fwd_pts
    )

    b = " " * BASE_INDENT
    sec_xml, seg_xml = emit_sections(
        stations, "s-ii_lh2", "S-II LH2 Tank Vessel", BASE_INDENT + 16
    )

    lox_xml = (
        f'{b}<fuelTank uID="s-ii_lox">\n'
        f"{b}    <name>S-II LOX Oxidizer Tank</name>\n"
        f"{b}    <description>"
        + _block(
            LOX_TANK_DESC.format(
                ring=BOLTING_RING_LENGTH / IN,
                dia=TANK_DIAMETER / IN,
                dia_m=TANK_DIAMETER,
                aft=COMMON_BULKHEAD_DEPTH / IN,
                haf=LOX_HALF_AXIS_FRACTION,
            ),
            BASE_INDENT + 8,
        )
        + f"\n{b}    </description>\n"
        f"{b}    <parentUID>{LOX_PARENT_UID}</parentUID>\n"
        f"{b}    <transformation>\n"
        f"{b}        <rotation>\n"
        f"{b}            <y>-90</y>\n"
        f"{b}        </rotation>\n"
        f"{b}        <translation>\n"
        f"{b}            <z>{LOX_TANK_Z:.4f}</z>\n"
        f"{b}        </translation>\n"
        f"{b}    </transformation>\n"
        f"{b}    <vessels>\n"
        f'{b}        <vessel uID="s-ii_lox_vessel">\n'
        f"{b}            <name>S-II LOX Tank Vessel</name>\n"
        f"{b}            <description>"
        + _block(
            LOX_VESSEL_DESC.format(
                ring=BOLTING_RING_LENGTH / IN, sta_eq=STA_LOX_EQUATOR
            ),
            BASE_INDENT + 16,
        )
        + f"\n{b}            </description>\n"
        f"{b}            <transformation />\n"
        f"{b}            <cylinderRadius>{R:.6f}</cylinderRadius>\n"
        f"{b}            <cylinderLength>{BOLTING_RING_LENGTH:.6f}</cylinderLength>\n"
        f"{b}            <domeType>\n"
        f"{b}                <ellipsoid>\n"
        f"{b}                    <halfAxisFraction>{LOX_HALF_AXIS_FRACTION:.6f}</halfAxisFraction>\n"
        f"{b}                </ellipsoid>\n"
        f"{b}            </domeType>\n"
        f"{b}        </vessel>\n"
        f"{b}    </vessels>\n"
        f"{b}</fuelTank>"
    )

    lh2_xml = (
        f'{b}<fuelTank uID="s-ii_lh2">\n'
        f"{b}    <name>S-II LH2 Fuel Tank</name>\n"
        f"{b}    <description>"
        + _block(
            LH2_TANK_DESC.format(
                sta_eq=STA_LOX_EQUATOR,
                above=STA_LOX_EQUATOR - STA_S2_DATUM,
                sta_datum=STA_S2_DATUM,
                dia=TANK_DIAMETER / IN,
                dia_m=TANK_DIAMETER,
                fwd=FORWARD_BULKHEAD_DEPTH / IN,
                aft=COMMON_BULKHEAD_DEPTH / IN,
            ),
            BASE_INDENT + 8,
        )
        + f"\n{b}    </description>\n"
        f"{b}    <parentUID>{LH2_PARENT_UID}</parentUID>\n"
        f"{b}    <transformation>\n"
        f"{b}        <rotation>\n"
        f"{b}            <y>-90</y>\n"
        f"{b}        </rotation>\n"
        f"{b}        <translation>\n"
        f"{b}            <z>{LH2_TANK_Z:.4f}</z>\n"
        f"{b}        </translation>\n"
        f"{b}    </transformation>\n"
        f"{b}    <vessels>\n"
        f'{b}        <vessel uID="s-ii_lh2_vessel">\n'
        f"{b}            <name>S-II LH2 Tank Vessel</name>\n"
        f"{b}            <description>"
        + _block(
            LH2_VESSEL_DESC.format(
                aft=COMMON_BULKHEAD_DEPTH,
                haf=LOX_HALF_AXIS_FRACTION,
                dvol=d_vol,
                ddev=d_dev,
            ),
            BASE_INDENT + 16,
        )
        + f"\n{b}            </description>\n"
        f"{b}            <transformation />\n"
        f"{b}            <sections>\n{sec_xml}\n{b}            </sections>\n"
        f"{b}            <segments>\n{seg_xml}\n{b}            </segments>\n"
        f"{b}        </vessel>\n"
        f"{b}    </vessels>\n"
        f"{b}</fuelTank>"
    )

    xml = lox_xml + "\n" + lh2_xml + "\n"

    # ---- report to stderr so that "- " (stdout) stays pipeable --------------
    log = sys.stderr.write
    log("S-II tank generation\n")
    log(f"  R                    = {R:.6f} m ({R / IN:.2f} in)\n")
    log(f"  LOX halfAxisFraction = {LOX_HALF_AXIS_FRACTION:.6f}\n")
    log(f"  LOX cylinderLength   = {BOLTING_RING_LENGTH:.6f} m\n")
    log(f"  LOX vessel length    = {LOX_VESSEL_LENGTH:.6f} m\n")
    log(f"  LOX origin convention= {LOX_VESSEL_ORIGIN}\n")
    log(f"  LOX origin offset    = {_LOX_ORIGIN_OFFSET:+.6f} m (rel. to LH2 origin)\n")
    log(f"  LOX fuelTank z       = {LOX_TANK_Z:.4f} m\n")
    log(
        f"  -> LOX fwd apex at LH2-local x = "
        f"{_LOX_ORIGIN_OFFSET + LOX_VESSEL_LENGTH:.6f} m "
        f"(must equal {COMMON_BULKHEAD_DEPTH:.6f})\n"
    )
    log("  Forward bulkhead compound meridian:\n")
    log(
        f"    r_k = {fwd_dome.r_k:.6f} m   a = {fwd_dome.a:.6f} m   "
        f"b = {fwd_dome.b:.6f} m   t_c = {fwd_dome.t_c:+.6f} m\n"
    )
    log(
        f"    phi_1 = {np.degrees(fwd_dome.phi_1):.3f} deg   "
        f"phi_2 = {np.degrees(fwd_dome.phi_2):.3f} deg   "
        f"rho = {fwd_dome.rho:.6f} m\n"
    )
    log(f"    residual = {fwd_dome.residual:.2e} m\n")
    log(f"    volume vs pure ellipsoid {d_vol:+.2f} %, max deviation {d_dev:.1f} mm\n")
    log(f"  LH2 sections = {len(stations)}, segments = {len(stations) - 1}\n")

    if dest == "-":
        sys.stdout.write(xml)
    else:
        with open(dest, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(xml)
        log(f"  written to {dest}\n")


if __name__ == "__main__":
    main()
