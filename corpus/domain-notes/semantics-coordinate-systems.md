# Coordinate systems: origin plus axes

A GMAT `CoordinateSystem` is fully defined by an **origin** (a celestial body,
barycenter, libration point, or spacecraft) and an **axes** type. The same
physical state is a different 6-vector in different systems; the physics is
unchanged. Four Earth systems always exist and need no `Create`:
`EarthMJ2000Eq`, `EarthMJ2000Ec`, `EarthFixed`, `EarthICRF`.

```
Create CoordinateSystem MoonMJ2000Eq;
MoonMJ2000Eq.Origin = Luna;
MoonMJ2000Eq.Axes   = MJ2000Eq;
```

Axes types you will reach for:

- **MJ2000Eq** — mean equator/equinox of J2000, inertial. The default Earth
  frame and the one GMAT integrates equations of motion in. Use for general
  Earth missions and as a report frame.
- **MJ2000Ec** — ecliptic of J2000. Natural for interplanetary geometry.
- **BodyFixed** — rotates with the body (Earth's is ITRF). Use for
  ground-relative geometry, longitude/latitude, surface targeting.
- **ICRF** — the realized inertial frame for high-precision/deep-space work.
- **ObjectReferenced** — built from the geometry of a primary and secondary
  object; this is how local orbit frames are defined. Burns commonly use the
  local **VNB** (velocity/normal/binormal) or **LVLH** (local
  vertical/local horizontal); relative motion uses **RIC**.
- **Topocentric** — local up/north/east at a `GroundStation`; for
  azimuth/elevation.

Guidance: integrate and do dynamics in an inertial frame (MJ2000Eq/ICRF); switch
to a body-fixed or topocentric frame only for *output* geometry. Never integrate
equations of motion in a rotating frame whose angular velocity is not modeled —
the velocity transform would be wrong. For a maneuver, the burn's `Local`
frame (`Origin` + `Axes = VNB/LVLH`) is usually what you want, not a global
inertial frame.
