# Applying an impulsive maneuver

An instantaneous delta-v is modeled with an `ImpulsiveBurn` resource and applied
in the mission sequence by the `Maneuver` command. The burn carries a frame and
three components; `Maneuver` stamps that delta-v onto a spacecraft at the
current epoch.

```
Create ImpulsiveBurn dv;
dv.CoordinateSystem = Local;   % Local => Origin + Axes define the frame
dv.Origin           = Earth;
dv.Axes             = VNB;     % Velocity / Normal / Binormal
dv.Element1         = 0.050;   % km/s along velocity (prograde)
dv.Element2         = 0;
dv.Element3         = 0;

BeginMissionSequence;
Propagate Prop(Sat) {Sat.Apoapsis};   % position the burn first
Maneuver dv(Sat);                      % apply the delta-v to Sat
```

Frame choice:

- `Axes = VNB` — components are along velocity, orbit normal, and binormal. A
  prograde burn (positive `Element1`) raises the opposite apsis; the most common
  in-plane case.
- `Axes = LVLH` — radial / along-track / cross-track relative to the local
  horizontal.
- For an **inertial** direction, set `CoordinateSystem` to a named inertial
  frame (e.g. `EarthMJ2000Eq`) instead of `Local`; the components are then in
  that frame.

`Element1/2/3` are the delta-v components in km/s. To model fuel use, set
`DecrementMass = true` and reference a `Tank` and `Isp`; otherwise the maneuver
is mass-free. The maneuver is instantaneous — there is no propagation across it,
so apply it at the geometric point you want (perigee, apogee, a node) by
propagating to that stopping condition first.
