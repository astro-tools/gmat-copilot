# Naming, references, and unused resources

Several validation issues are about how resources are named and wired together.

- **Duplicate name.** Every resource must have a unique name; `Create Spacecraft
  Sat;` twice, or a `Spacecraft` and a `Variable` both named `Sat`, is a
  conflict. GMAT may silently keep one and drop the other, so the linter flags
  it — two objects fighting over one name is almost never intended.

- **Undeclared reference.** A field that points at another resource must name one
  that exists: `Prop.FM = FM;` requires a `Create ForceModel FM;`,
  `Sat.Tanks = {tank1};` requires `tank1`. Referencing a name that was never
  created is an error. GMAT permits some forward references (you may name a
  resource before its `Create` appears textually), so the check is about
  existence anywhere in the script, not ordering.

- **Reference-target mismatch.** A reference must point at the *right kind* of
  resource. `Prop.FM = Sat;` (a Propagator's force-model slot pointed at a
  Spacecraft) or `Sat.Thrusters = {tank1};` (a thruster slot given a tank) are
  type-correct names pointing at the wrong target type.

- **Unused resource (advisory).** A resource created but never referenced —
  never propagated, reported, maneuvered, or wired into another object — is
  usually dead configuration left over from editing. This is informational, not
  an error: the script still runs. But an unused `ForceModel`, `Propagator`, or
  `Spacecraft` often signals a missing connection (e.g. you forgot
  `Prop.FM = FM;`).

```
Create ForceModel FM;
Create Propagator Prop;
Prop.FM = FM;                 % every Propagator must reference a ForceModel
Create Spacecraft Sat;
BeginMissionSequence;
Propagate Prop(Sat) {Sat.ElapsedDays = 1};
```
