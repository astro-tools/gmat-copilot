# Composing a force model for the regime

A `ForceModel` bundles the accelerations acting on the spacecraft. Composing it
to match the mission regime is the single biggest driver of physical accuracy —
too little and the trajectory is wrong; too much and the run is slow with no
benefit.

```
Create ForceModel FM;
FM.CentralBody = Earth;
FM.PrimaryBodies = {Earth};                 % the body whose gravity field is modeled
FM.GravityField.Earth.Degree = 8;           % non-spherical harmonics
FM.GravityField.Earth.Order  = 8;
FM.PointMasses = {Luna, Sun};               % third bodies as point masses
FM.Drag = MSISE90;                          % atmosphere model (LEO)
FM.SRP  = On;                               % solar radiation pressure
```

What each term contributes, and when it matters:

- **Point-mass central body** — the two-body term, always present. A
  `PointMasses = {Earth}` model is two-body only and is fine for quick geometry
  but omits all secular drift.
- **Non-spherical gravity** (`PrimaryBodies` + `GravityField.<Body>.Degree/Order`)
  — J2 (degree 2) drives nodal regression and apsidal rotation; needed for any
  realistic LEO/SSO. GEO needs the C22/S22 tesseral terms for longitude drift.
  Typical degree/order: LEO 8×8 to 70×70, GEO 4×4, MEO 12×12.
- **Third bodies** (`PointMasses`) — Sun and Moon matter for MEO/GEO/HEO and are
  dominant in cislunar. Omitting the Sun in cislunar causes km-scale errors.
- **Drag** — only below ~1000 km; needs `DryMass`, `Cd`, `DragArea` on the
  spacecraft. Negligible (and just noise) at high altitude.
- **SRP** — matters for high area-to-mass and long arcs (GEO, interplanetary);
  always pair with a shadow model so it switches off in eclipse.
- **Relativity** — usually off for Earth orbits; on for precision MEO (GPS) and
  deep space.

Match integrator tolerance to fidelity: a 70×70 field with a loose tolerance
wastes effort, and drag above 1500 km adds nothing.
