# Setting a spacecraft's orbit and common regimes

A spacecraft's initial orbit is set by its epoch, a display state type, and the
matching state fields. Keplerian input is the most natural for a named orbit:

```
Create Spacecraft Sat;
Sat.DateFormat       = UTCGregorian;
Sat.Epoch            = '01 Jan 2025 12:00:00.000';
Sat.CoordinateSystem = EarthMJ2000Eq;
Sat.DisplayStateType = Keplerian;
Sat.SMA  = 7000;     % km
Sat.ECC  = 0.001;
Sat.INC  = 28.5;     % deg
Sat.RAAN = 0;
Sat.AOP  = 0;
Sat.TA   = 0;
```

The state fields must match `DisplayStateType`: Keplerian uses
`SMA ECC INC RAAN AOP TA`; Cartesian uses `X Y Z VX VY VZ`. Do not mix the two
sets in one block.

Common regimes (Earth, radius ≈ 6378 km, μ ≈ 398600 km³/s²):

- **LEO** — `SMA` ≈ 6700–7200 (≈ 300–800 km altitude), `ECC` ≈ 0, any `INC`.
  ISS-like: `SMA = 6778`, `INC = 51.6`. Drag matters; use a real atmosphere
  model.
- **GEO** — geostationary radius is `SMA = 42164`, `ECC = 0`, `INC = 0`. Period
  is one sidereal day; the satellite holds a fixed longitude. Tesseral gravity
  (C22/S22), Sun, and Moon drive east-west and north-south drift.
- **MEO** — e.g. GPS at `SMA ≈ 26560`, `INC = 55`.
- **HEO / Molniya** — high eccentricity (`ECC ≈ 0.74`), `INC = 63.4`
  (the critical inclination that freezes argument of perigee), 12-hour period.

For a precise circular altitude `h`, `SMA = 6378.1363 + h`. For a target
period `T`, `SMA = (mu * (T / (2*pi))^2)^(1/3)`.
