# Time systems and epoch formats

A spacecraft's `Epoch` is interpreted according to its `DateFormat`. The format
encodes both a **time system** (which physical clock) and a **representation**
(Gregorian calendar string or a modified Julian day count).

```
Create Spacecraft Sat;
Sat.DateFormat = UTCGregorian;
Sat.Epoch      = '01 Jan 2025 12:00:00.000';
```

Time systems you will meet:

- **UTC** — civil time with leap seconds. The usual choice for human-entered
  epochs (`UTCGregorian`).
- **TAI** — continuous atomic time, no leap seconds.
- **A.1** — GMAT's internal atomic scale (TAI + 0.0343817 s); the default
  `A1ModJulian`.
- **TT** — terrestrial dynamical time (TAI + 32.184 s); used in
  precession/nutation.
- **TDB** — barycentric dynamical time; used for planetary ephemeris lookup.

Representations:

- **Gregorian** — `'DD Mon YYYY HH:MM:SS.sss'`, e.g.
  `'21 Jul 2014 11:29:10.811'`. Quoted, human-readable.
- **ModJulian** — a Julian day count. **GMAT's modified Julian date uses
  reference epoch 05 Jan 1941 12:00:00 (offset 2 430 000.0)** — it is *not* the
  standard MJD (offset 2 400 000.5); the two differ by 29 999.5 days. Do not feed
  a standard-MJD value into a GMAT ModJulian field.

So `DateFormat` values pair a system with a representation: `UTCGregorian`,
`A1ModJulian`, `TAIModJulian`, `TTGregorian`, `TDBModJulian`, and so on.

Practical notes: enter epochs as `UTCGregorian` for clarity; GMAT integrates
internally in an atomic scale regardless. Epoch parameters used in conditions
follow the same systems — e.g. `Sat.TAIModJulian`, `Sat.UTCGregorian`. Leap-second
and Earth-orientation data come from GMAT's data files; stale files shift UTC
conversions by an integer second.
