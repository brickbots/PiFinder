# The chart's center object comes from the drawn markers, not the Nearby ranking

The chart can name the object it is pointed at, on an optional readout along
the bottom (the **center-object readout**, `chart_center_object`). Deciding
*which* object that is looks trivial until you notice the codebase already
answers a very similar question two different ways, and neither is the right
one here.

`ClosestObjectsFinder` (ADR 0030) will rank the whole filtered catalog by
angular distance from the pointing, nearest first. That is what the object
list's **Nearby** sort uses. The chart's own marker layer uses the other query
on the same index, `get_objects_within_radius`, and then throws most of the
result away: objects fainter than `dso_mag_limit(fov)` are dropped, and what
survives is capped at the 20 brightest.

Reaching for the Nearby ranking is the obvious move and it is wrong. It would
happily name a magnitude 14 galaxy that the chart deliberately chose not to
draw, or, pointed at blank sky, an object 25 degrees off-screen. The user reads
"IC 5070", looks at the middle of the chart, and sees nothing there. A readout
that names things you cannot see is worse than no readout.

## The rule

The center object is the marker nearest the center of the chart, drawn from
exactly the set the chart plotted on the current solve, restricted to markers
that fall inside the screen bounds. Nothing else is a candidate.

Three consequences follow, and all three are intended:

With **DSO Display** off, `plot_markers` returns after the target cross, so the
target is the only candidate. The readout goes quiet on a chart with no markers
on it. That is the invariant doing its job, not a bug.

The magnitude limit and the 20-marker cap apply, because they already applied
to the drawing. The readout inherits whatever the chart decided was worth
showing at this zoom level.

An off-screen target does not count. It degrades to an edge pointer rather than
a cross, and an edge pointer is not something you can be said to be pointed at.

Distance is measured in screen pixels from the chart center, not in great-circle
degrees. Below about 20 degrees of field the two agree to within a pixel, but
the chart zooms out to 60 degrees, where the projection stretches the corners
and the orderings genuinely diverge. "Nearest the center of the chart" is a
statement about the chart, so measure it on the chart. The screen coordinates
are needed for the bounds check anyway.

## Sticky between solves

The ranking is recomputed on every new solve, one or two times a second. Two
markers sitting near-equidistant from the center will swap places on IMU jitter
alone, and since the readout marquee-scrolls, a swap restarts the scroll. A
long name would never finish a pass.

So the center object is held: once chosen it keeps the line until a rival is
closer by a clear margin, or until it drops out of the drawn or on-screen set.
The margin is a fraction of the current distance rather than a fixed pixel
count, so it scales with the zoom level. A deliberate slew moves the pointing
far enough to clear the margin immediately, so the stickiness costs nothing
when the user actually means to change what they are looking at.

A dwell timer was the alternative and it is worse. It ignores a real slew for
as long as it runs, which is exactly when the user most wants the readout to
keep up.
