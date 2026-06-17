# Sun-synchronous orbits

A sun-synchronous orbit (SSO) keeps a fixed local solar time at the ascending
node by choosing the orbit so its right ascension of the ascending node
precesses at exactly the rate the Earth orbits the Sun: about +0.9856°/day
(360° per 365.25 days), eastward.

The precession comes from the J2 oblateness term, whose secular nodal rate is

```
RAAN_dot = -(3/2) * n * J2 * (R_earth / p)^2 * cos(INC)
```

with `n = sqrt(mu / SMA^3)`, `p = SMA * (1 - ECC^2)`, `J2 ≈ 1.08263e-3`,
`R_earth ≈ 6378.137`. Because `cos(INC)` must be negative to give an eastward
(positive) drift, SSO inclinations are **retrograde** — just above 90°. For a
near-circular LEO this lands near `INC ≈ 96°–99°`; e.g. a 600 km circular
SSO needs `INC ≈ 97.8°`.

Script shape — set the regime in Keplerian and let a J2-or-better force model
produce the precession:

```
Create Spacecraft Sat;
Sat.DisplayStateType = Keplerian;
Sat.SMA  = 6978;        % ~600 km altitude
Sat.ECC  = 0.001;
Sat.INC  = 97.8;        % retrograde, near-polar
Sat.RAAN = 45;
Sat.AOP  = 0;
Sat.TA   = 0;

Create ForceModel FM;
FM.CentralBody = Earth;
FM.PrimaryBodies = {Earth};
FM.GravityField.Earth.Degree = 8;
FM.GravityField.Earth.Order  = 8;   % must include J2 (degree >= 2)
```

A point-mass-only force model will *not* precess the node, so an SSO modeled
with `PointMasses = {Earth}` is physically wrong — you need a non-spherical
gravity field (at least degree/order 2) for the sun-synchronous behavior to
appear.
