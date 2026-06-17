# Choosing and tuning a propagator

A `Propagator` binds a numerical integrator to a `ForceModel`. The integrator
turns the modeled accelerations into a trajectory; its type and tolerances trade
speed against accuracy.

```
Create Propagator Prop;
Prop.FM           = FM;            % the force model to integrate
Prop.Type         = RungeKutta89;
Prop.InitialStepSize = 60;        % seconds
Prop.Accuracy     = 1e-11;
Prop.MinStep      = 0;
Prop.MaxStep      = 2700;
Prop.MaxStepAttempts = 50;
```

Integrator types:

- **RungeKutta89 / PrinceDormand78** — high-order adaptive Runge-Kutta; the
  general-purpose default for most smooth orbital dynamics. RK89 is GMAT's common
  choice.
- **RungeKutta68 / PrinceDormand45 / RungeKutta56** — lower order; adequate for
  coarse or short propagations.
- **AdamsBashforthMoulton** — a multistep predictor-corrector; efficient for long
  arcs with smooth, expensive force evaluations.
- **BulirschStoer** — extrapolation method for high accuracy on smooth problems.
- **SPK** — reads a pre-built SPICE kernel instead of integrating; for replaying
  an existing ephemeris.

Tuning:

- `Accuracy` is the per-step error target for the adaptive step controller.
  Match it to the force-model fidelity — 1e-11 with an 8×8 field is reasonable;
  1e-6 wastes a 70×70 field.
- `MaxStep` caps the step so the integrator cannot skip over a stopping condition
  or a fast-changing perturbation; set it well under the orbital period for
  eccentric orbits.
- Each `Propagate` command names one propagator; cislunar and interplanetary
  missions typically use two — one per central-body phase — and GMAT does not
  switch central bodies automatically.
