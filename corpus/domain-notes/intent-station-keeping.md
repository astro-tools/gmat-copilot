# Basic station-keeping

Station-keeping holds an orbit against perturbations by periodically correcting
the element that has drifted. The script pattern is a loop that propagates until
the controlled quantity leaves a deadband, then applies a small corrective
maneuver — often sized by a targeter.

GEO east-west example (hold longitude by trimming semi-major axis, which sets the
drift rate):

```
Create ImpulsiveBurn sk;   sk.Axes = VNB;
Create DifferentialCorrector DC;
Create Variable cycle;

BeginMissionSequence;
For cycle = 1:1:10;
   Propagate Prop(Sat) {Sat.ElapsedDays = 14};     % a keeping cycle
   Target DC {SolveMode = Solve, ExitMode = DiscardAndContinue};
      Vary    DC(sk.Element1 = 0, {Perturbation = 1e-5, Lower = -0.05, Upper = 0.05, MaxStep = 0.01});
      Maneuver sk(Sat);
      Achieve DC(Sat.Earth.SMA = 42164, {Tolerance = 0.5});
   EndTarget;
EndFor;
```

Patterns and considerations:

- **Deadband logic** can also be expressed with `While`/`If` on the drifting
  parameter (e.g. `If Sat.Earth.SMA < 42163` ... maneuver), rather than a fixed
  cycle.
- The maneuver is small; bound the `Vary` tightly so the corrector does not
  wander into a large, unphysical burn.
- Station-keeping only makes sense against a realistic force model — the drift
  you are correcting comes from tesseral gravity (GEO longitude),
  Sun/Moon third-body (inclination), or drag (LEO altitude). With a point-mass
  model there is nothing to keep station against.
- Track fuel with `Sat.TotalMass` and a mass-decrementing burn if the delta-v
  budget matters.
