# Two-story core-and-perimeter layout

Footprint 76.2 m × 60.96 m (250 ft × 200 ft). Each floor uses four perimeter zones and one core zone.

```
North (y=max)
+---------------------------+
|      zone-f*-north        |
| +-----------------------+ |
| | zone-f*-core          | |
|W|                       |E
| |                       | |
| +-----------------------+ |
|      zone-f*-south        |
+---------------------------+
West (x=0)              East (x=max)

Floor 1: `rtu-1` → `vav-f1-{core,north,east,south,west}`
Floor 2: `rtu-2` → `vav-f2-{core,north,east,south,west}`
```

Climate: **ASHRAE 4A**, weather file `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw` (Chicago O'Hare TMY3).