# Orbit transfer with a targeted differential corrector

A Hohmann-style transfer raises an orbit with two burns: one to push apoapsis
out to the target radius, a second at apoapsis to circularize. Rather than
hand-computing the delta-v magnitudes, let a `DifferentialCorrector` solve for
them inside a `Target` block. `Vary` declares the unknowns, `Achieve` declares
the goals, and the solver iterates the burns until the goals are met.

```
Create ImpulsiveBurn TOI;   TOI.Axes = VNB;   % transfer-orbit injection
Create ImpulsiveBurn GOI;   GOI.Axes = VNB;   % goal-orbit insertion
Create DifferentialCorrector DC;

BeginMissionSequence;
Propagate Prop(Sat) {Sat.Periapsis};

Target DC {SolveMode = Solve, ExitMode = DiscardAndContinue};
   Vary    DC(TOI.Element1 = 0.5, {Perturbation = 1e-4, Lower = 0, Upper = 3, MaxStep = 0.2});
   Maneuver TOI(Sat);
   Propagate Prop(Sat) {Sat.Apoapsis};
   Achieve DC(Sat.Earth.RMAG = 42165, {Tolerance = 0.1});

   Vary    DC(GOI.Element1 = 0.5, {Perturbation = 1e-4, Lower = 0, Upper = 3, MaxStep = 0.2});
   Maneuver GOI(Sat);
   Achieve DC(Sat.Earth.ECC = 0, {Tolerance = 1e-3});
EndTarget;
```

Ordering is the crux:

- A `Vary` must come **before** the command that consumes the value it sets — so
  `Vary TOI.Element1` precedes `Maneuver TOI`.
- An `Achieve` must come **after** the commands that produce the quantity it
  checks — so the apoapsis `Achieve RMAG` follows the propagate-to-apoapsis.
- `TOI.Element1` is the burn-frame velocity component (V in VNB). Give a
  reasonable initial guess; tight `Lower`/`Upper` bounds keep the solver stable.
- `SolveMode = Solve` runs the corrector; `ExitMode` controls what happens to the
  solved state when the block ends.

The same `Target`/`Vary`/`Achieve` shape generalizes to plane changes,
phasing, and B-plane targeting — only the unknowns and goals change.
