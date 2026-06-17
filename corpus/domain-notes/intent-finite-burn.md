# Modeling a finite (continuous) burn

A finite burn applies thrust over a time interval, consuming fuel, rather than
an instantaneous delta-v. It needs four resources wired together — a tank, a
thruster that draws from it, the spacecraft that carries both, and a
`FiniteBurn` that switches the thruster on and off.

```
Create ChemicalTank tank1;
tank1.FuelMass = 725;

Create ChemicalThruster engine1;
engine1.CoordinateSystem = Local;
engine1.Origin           = Earth;
engine1.Axes             = VNB;
engine1.ThrustDirection1 = 1;     % unit direction in the burn frame
engine1.ThrustDirection2 = 0;
engine1.ThrustDirection3 = 0;
engine1.Tank             = {tank1};

Create Spacecraft Sat;
Sat.Tanks     = {tank1};          % the spacecraft must carry both
Sat.Thrusters = {engine1};

Create FiniteBurn fb;
fb.Thrusters = {engine1};         % the burn drives this thruster

BeginMissionSequence;
BeginFiniteBurn fb(Sat);          % thrust ON
Propagate Prop(Sat) {Sat.ElapsedSecs = 600};   % thrust applied across this arc
EndFiniteBurn fb(Sat);            % thrust OFF
```

Key rules:

- The thrust is active **only** between `BeginFiniteBurn` and `EndFiniteBurn`;
  everything propagated in that span feels it. The pair must reference the same
  `FiniteBurn` and the same spacecraft.
- The spacecraft must list both the tank (`Tanks`) and the thruster
  (`Thrusters`), and the thruster must reference the tank (`Tank = {tank1}`) — a
  thruster with no tank has no propellant.
- Thrust and Isp are set on the thruster (`ChemicalThruster` uses polynomial
  coefficients such as `C1`, `K1`; an `ElectricThruster` uses its own model).
- Use a finite burn when burn duration is a meaningful fraction of the orbit or
  when fuel mass history matters; use an `ImpulsiveBurn` otherwise.
