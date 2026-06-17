# If / While conditions are simple comparisons joined by & and |

The condition in an `If`, `While`, or `NonlinearConstraint` is a logical
expression built from comparisons. GMAT is strict about its shape, and a few
habits from other languages do not carry over.

- Comparison operators: `<  <=  >  >=  ==  ~=`. Note `~=` (not `!=`) for
  "not equal".
- Combine conditions with `&` (and) and `|` (or). The words `and`/`or` and the
  doubled C-style `&&`/`||` are **not** GMAT logical operators here.
- Each side of a comparison must be a parameter, variable, array element, or a
  numeric literal. You cannot test a resource handle or a bare object.
- A condition must actually be a comparison: a lone parameter
  (`While Sat.ElapsedDays`) is not a boolean and is rejected — write
  `While Sat.ElapsedDays < 1`.

```
If Sat.Earth.RMAG > 42000 & Sat.Earth.ECC < 0.01
   Propagate Prop(Sat) {Sat.Periapsis};
EndIf;

While Sat.ElapsedDays < 5 | Sat.Earth.TA < 90
   Propagate Prop(Sat) {Sat.Apoapsis};
EndWhile;
```

Do not confuse this with the `For` loop, whose header is a MATLAB-style
colon range, not a logical test: `For I = 1:1:5`. The loop counter must be a
`Create`d `Variable`. Mixing the two — putting a colon range in a `While`, or a
comparison in a `For` — is a structural error.
