# Writing ephemeris and report output

Two subscriber resources capture mission output to files: `ReportFile` for
tabular parameter logs, and `EphemerisFile` for standard ephemeris products.

Tabular report:

```
Create ReportFile rf;
rf.Filename     = 'mission.report';
rf.Precision    = 16;
rf.WriteHeaders = true;
rf.Add          = {Sat.A1ModJulian, Sat.Earth.SMA, Sat.Earth.ECC, Sat.TotalMass};

BeginMissionSequence;
Propagate Prop(Sat) {Sat.ElapsedDays = 1};
Report rf Sat.A1ModJulian Sat.Earth.SMA;   % optional one-off line
```

`ReportFile.Add` logs the listed parameters every integration step; the separate
`Report` command writes a single ad-hoc row. Both can target the same file.

Ephemeris output (e.g. CCSDS-OEM):

```
Create EphemerisFile eph;
eph.Spacecraft   = Sat;
eph.Filename     = 'sat.oem';
eph.FileFormat   = 'CCSDS-OEM';     % also SPK, Code-500, STK-TimePosVel
eph.CoordinateSystem = EarthMJ2000Eq;
eph.StepSize     = 60;              % seconds; or 'IntegratorSteps'
```

Notes:

- `EphemerisFile.FileFormat` selects the product: `CCSDS-OEM` (text orbit
  ephemeris message), `SPK` (binary SPICE kernel), `Code-500`, `STK-TimePosVel`.
- The ephemeris spans whatever the spacecraft propagates after
  `BeginMissionSequence`; the file is written incrementally and finalized at the
  end of the run.
- Choose the coordinate system deliberately — an OEM is only meaningful with its
  stated frame and time system. `EarthMJ2000Eq` is the usual inertial default.
- For deterministic, machine-readable output in automated workflows, prefer
  `ReportFile`/`EphemerisFile` to interactive subscribers.
