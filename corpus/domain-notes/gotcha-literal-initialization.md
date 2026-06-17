# Resource setup takes literals, not expressions

A GMAT script has two phases: the **resource-configuration** section before
`BeginMissionSequence`, and the **mission sequence** after it. Field assignments
in the configuration section initialize a resource's *attributes*. They accept
only literal values (numbers, quoted strings, enum keywords) or handles to
other resources — never arithmetic, function calls, or references to another
resource's live state.

Wrong (rejected — the right-hand side is an expression / live parameter):

```
Create Spacecraft Sat;
Sat.SMA = 6378 + 500;          % arithmetic not allowed here
Sat.TA  = Sat2.TA;             % cannot read another object's state at setup
```

Right — use literals at setup, and compute in the mission sequence:

```
Create Spacecraft Sat;
Sat.SMA = 6878;

Create Variable r;
BeginMissionSequence;
r = 6378 + 500;                % arithmetic belongs in the sequence
Sat.SMA = r;                   % assigning a computed value is fine here
```

Why: before `BeginMissionSequence` GMAT is building objects, not running a
program, so there is no evaluation context — the parser only knows how to store
a constant into a field. Expressions, `Variable` reads, and parameter
references only have meaning once the sequence is executing. The same rule is
why you set an `Array` element with a literal at setup but compute it with an
assignment command after `BeginMissionSequence`.

Handles are the exception: `Prop.FM = MyForceModel;` or `Sat.Tanks = {tank1};`
are references to other resources by name, resolved at initialization, and are
expected.
