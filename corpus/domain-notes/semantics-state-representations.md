# State representations

A spacecraft's orbit state is six numbers, but which six depends on the
`DisplayStateType`. The representation is a presentation/input choice — GMAT
converts to its internal Cartesian state regardless — so pick the one that makes
the intended orbit easiest to express. The state fields you set must match the
chosen type.

- **Cartesian** — `X Y Z VX VY VZ` (km, km/s) in the spacecraft's
  `CoordinateSystem`. Use when you have a position/velocity vector directly
  (e.g. from an ephemeris or a TLE conversion), or for hyperbolic/degenerate
  orbits where elements are ill-defined.

- **Keplerian** — `SMA ECC INC RAAN AOP TA` (km, –, deg). The natural way to
  state a named orbit: altitude via SMA, shape via ECC, orientation via the
  angles. Singular when ECC = 0 (AOP undefined) or INC = 0 (RAAN undefined).

- **ModifiedKeplerian** — `RadApo RadPer INC RAAN AOP TA`; uses apoapsis and
  periapsis radii instead of SMA/ECC. Convenient when you know the apsis
  altitudes (e.g. a transfer or Molniya orbit).

- **SphericalAZFPA / SphericalRADEC** — magnitude, angles, and flight-path or
  right-ascension/declination of velocity. Useful for launch/ascent and
  asymptote conditions.

- **Equinoctial / ModifiedEquinoctial** — nonsingular elements that stay
  well-defined at zero eccentricity and inclination; good for near-circular,
  near-equatorial orbits and for smooth optimization.

- **Others** — `Delaunay`, `Planetodetic`, `OutgoingAsymptote`,
  `IncomingAsymptote`, `BrouwerMeanShort`, `BrouwerMeanLong` for specialized
  analyses.

```
Sat.DisplayStateType = ModifiedKeplerian;
Sat.RadApo = 42164;   Sat.RadPer = 6678;
Sat.INC = 28.5;       Sat.RAAN = 0;   Sat.AOP = 0;   Sat.TA = 0;
```

Rule: never mix field sets — set every field of one representation, and let GMAT
report any other representation you need as a parameter (e.g. `Sat.Earth.SMA`).
