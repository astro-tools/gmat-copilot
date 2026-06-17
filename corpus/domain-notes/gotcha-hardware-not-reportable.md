# Hardware fields are settings, not reportable parameters

Resource fields divide into two kinds. **Parameters** are time-varying,
queryable quantities a spacecraft exposes — `Sat.Earth.SMA`, `Sat.TotalMass`,
`Sat.ElapsedSecs` — and they are valid in `Report`, `ReportFile.Add`, stopping
conditions, `If`/`While` tests, and `Vary`/`Achieve`. **Configuration fields**
are the attributes you set on a resource at build time; most hardware fields
fall in this group and are *not* reportable.

Wrong (rejected — a thruster/tank attribute is not a spacecraft parameter):

```
Report rf tank1.FuelMass;          % FuelMass is a tank setting, not a parameter
Report rf engine1.ThrustDirection1;
```

Report the spacecraft-level quantities instead:

```
Report rf Sat.TotalMass;           % includes dry mass + remaining fuel
Report rf Sat.tank1.FuelMass;      % fuel exposed *through* the spacecraft
```

Why: `Report` and friends operate on the *Parameter* system, which is keyed to
objects (spacecraft, burns, variables) that publish observable values during
propagation. A tank's `FuelMass` set in configuration is an initial condition,
not a published parameter — the live, decremented fuel is surfaced on the
spacecraft that owns the tank (`Sat.<tankName>.FuelMass`,
`Sat.TotalMass`). The general signal: if a field is something you *assign* to
shape the model, it is configuration; if it is something the simulation
*produces*, it is a parameter. Only the latter can be reported, plotted, or used
in a condition.
