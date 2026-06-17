# Visualizing an orbit and ground track

Visualization resources are *subscribers*: they are created in the configuration
section, listing what they should draw, and they update automatically as the
mission sequence propagates.

3-D orbit view:

```
Create OrbitView view;
view.Add               = {Sat, Earth};      % objects to draw
view.CoordinateSystem  = EarthMJ2000Eq;
view.ViewPointReference = Earth;
view.ViewPointVector    = [30000 0 30000];
view.ViewDirection      = Earth;
```

2-D ground track:

```
Create GroundTrack gt;
gt.Add = {Sat};                              % traces sub-satellite point
```

An XY plot of any parameters over time:

```
Create XYPlot plot;
plot.XVariable  = Sat.A1ModJulian;
plot.YVariables = {Sat.Earth.Altitude};
```

Notes:

- `Add = {…}` is the universal "what to draw/log" field on subscribers; it takes
  a brace list of objects (for views) or parameters (for plots and reports).
- Newer GMAT releases also ship an OpenFrames-based viewer
  (`OpenFramesInterface` + `OpenFramesView`) used by many recent samples; the
  classic `OrbitView` remains valid and is the simplest choice.
- Subscribers draw whatever propagates after `BeginMissionSequence`; you do not
  call them explicitly. To see a full orbit, propagate at least one period.
- Visualization has no effect on dynamics — it is purely output. For headless or
  batch runs, prefer a `ReportFile` or `EphemerisFile` over interactive views.
