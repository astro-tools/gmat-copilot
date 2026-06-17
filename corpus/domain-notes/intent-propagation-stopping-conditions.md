# Propagating to a stopping condition

The `Propagate` command advances one or more spacecraft under a propagator until
a stopping condition in braces is met. The condition is what makes propagation
expressive — you rarely propagate "for a while", you propagate *to an event*.

```
Propagate Prop(Sat) {Sat.ElapsedSecs = 3600};   % exactly one hour
Propagate Prop(Sat) {Sat.ElapsedDays = 1.5};
Propagate Prop(Sat) {Sat.Apoapsis};              % to next apogee
Propagate Prop(Sat) {Sat.Periapsis};             % to next perigee
Propagate Prop(Sat) {Sat.Earth.TA = 90};         % to a true anomaly
Propagate Prop(Sat) {Sat.Earth.RMAG = 42000};    % to a geocentric radius
Propagate Prop(Sat) {Sat.UTCGregorian = '15 Jul 2030 00:00:00.000'};  % to an epoch
```

Notes:

- **Apsides** (`Sat.Apoapsis`, `Sat.Periapsis`) are special keywords, not
  numeric equalities — GMAT detects the turning point. They are the idiomatic way
  to position a maneuver.
- **Elapsed** conditions (`ElapsedSecs`, `ElapsedDays`) are relative to the start
  of *this* propagate; negative values propagate **backward** in time.
- **Parameter-equals-value** conditions stop the first time the parameter crosses
  the target. Body-dependent parameters take a body qualifier
  (`Sat.Earth.TA`); the engine brackets and refines the crossing to
  `StopTolerance`.
- Multiple spacecraft in one call stay time-synchronized:
  `Propagate Prop(SatA, SatB) {SatA.ElapsedDays = 1};`.
- A single brace list may hold several conditions; propagation stops at whichever
  occurs first.

Pick the condition that names the *geometry* you care about (an apsis, a node, a
radius, an epoch) rather than guessing an elapsed time — it makes the script
robust to changes in the orbit.
