# Field names, value types, and enumerations are exact

GMAT validates every field assignment against the resource's definition. Three
related errors come from getting a field, its value type, or its allowed
keyword wrong.

- **Unknown field.** Field names are case-sensitive and often terse. It is
  `Sat.AOP` not `ArgPer`, `Sat.INC` not `Inclination`, `Sat.RAAN` not
  `LongAscNode`, `FM.PointMasses` not `PointMass`. A field that does not exist on
  the resource is rejected outright — there is no silent ignore.

- **Type mismatch.** Each field expects a specific value kind: a real number, an
  integer, a boolean (`true`/`false`, lowercase), a quoted string, an enum
  keyword, or a brace list. `Sat.SMA = 'high';` (string into a real),
  `rf.WriteHeaders = Yes;` (should be `true`), or `FM.PointMasses = Earth;`
  (should be the list `{Earth}`) are all type errors.

- **Enum violation.** Many fields accept only a fixed vocabulary. Use the exact
  spelling: `Sat.DisplayStateType = Keplerian;` (not `Kepler`),
  `Prop.Type = RungeKutta89;`, `burn.Axes = VNB;`, `FM.Drag = MSISE90;`. A value
  outside the allowed set is rejected even though it is the right *type*.

```
Create Spacecraft Sat;
Sat.DisplayStateType = Keplerian;   % valid enum
Sat.SMA  = 7000;                    % real
Sat.INC  = 28.5;                    % canonical field name

Create ForceModel FM;
FM.PointMasses = {Earth, Luna};     % brace list, not a bare name
```

Why: GMAT resources are strongly typed objects reflected from the engine's
object model. When unsure of a field name, its type, or its allowed values,
prefer the canonical forms shown in the reference pages and sample scripts
rather than guessing a natural-language synonym.
