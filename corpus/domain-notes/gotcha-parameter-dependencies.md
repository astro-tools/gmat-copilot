# Orbit parameters need the right dependency qualifier

Many spacecraft parameters are only meaningful with respect to a **central
body** or a **coordinate system**, and GMAT requires you to name that
dependency explicitly in the parameter. Getting the qualifier wrong (or omitting
a required one) is a frequent mistake.

Two families:

- **Body-dependent** parameters — orbital elements and body-relative geometry.
  Qualify with a celestial body: `Sat.Earth.SMA`, `Sat.Earth.ECC`,
  `Sat.Earth.RMAG`, `Sat.Luna.Periapsis`, `Sat.Earth.Altitude`. The body says
  "compute this element relative to *that* gravitational center." `Sat.SMA`
  works as shorthand when the spacecraft's own central body is unambiguous, but
  the qualified form is safer in multi-body missions.

- **Coordinate-system-dependent** parameters — Cartesian components and frame
  geometry. Qualify with a coordinate system: `Sat.EarthMJ2000Eq.X`,
  `Sat.EarthMJ2000Eq.VZ`, `Sat.MoonMJ2000Eq.BdotR`. The frame says "express this
  vector component in *that* frame."

```
% body-dependent (element)
Report rf Sat.Earth.SMA Sat.Earth.ECC;
% coordinate-system-dependent (component)
Report rf Sat.EarthMJ2000Eq.X Sat.EarthMJ2000Eq.VX;
```

Why it matters: the same spacecraft has a different SMA about Earth than about
the Moon, and a different X in MJ2000Eq than in a body-fixed frame. Pairing a
body-dependent element with a coordinate system (e.g. `Sat.EarthMJ2000Eq.SMA`)
or a frame component with a body (`Sat.Earth.X`) is a dependency mismatch and is
rejected. When a parameter takes no dependency (e.g. `Sat.TotalMass`,
`Sat.A1ModJulian`), do not add one.
