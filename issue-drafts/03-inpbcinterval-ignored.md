# INPBCINTERVAL has no effect: full INP3 updates go out every 10 minutes regardless
labels: xrouter-bug, inp3, reported
state: open

## What happens

XRouter sends a full RIF update (its own node and everything it knows) to every INP3 neighbour every 10 minutes counted from start-up, whatever INPBCINTERVAL is set to. With `INPBCINTERVAL=120`, full updates went out at these times after start-up:

```
505a: 604, 1208 s
505c: 610, 1214 s
505o: 607, 1211 s
```

`N BC T` shows the configured interval and a "Next Full Update" time that then passes with nothing sent. On 505o, 14 minutes into a run:

```
INP3 Unicast Times:
  Interval (secs):      120
  Last Full Update:     13:40:11
  Next Full Update:     13:42:11
  Last Unscheduled:     13:40:21
```

Early in a run it shows `Last Full Update: ---` and `Next Full Update: ---`. With INPBCINTERVAL left unset, `N BC T` shows an interval of 3600.

## Expected

MAN XROUTER.CFG: "INPBCINTERVAL  Secs between scheduled INP3 unicasts (600)". MAN INP3: "Positive information is not time critical and, like NetRom nodes broadcasts, is sent at scheduled intervals only." So with `INPBCINTERVAL=120` a full update every 2 minutes, at the "Next Full Update" time `N BC T` shows, and with it unset a default of 600 seconds.

## How to reproduce

1. XROUTER.CFG with `INPBCINTERVAL=120` (and a short `L3RTTINTERVAL`, for example 30) and one AXUDP port to an INP3 neighbour.
2. Let the link come up and keep the network still.
3. Watch the RIFs XRouter sends: after the ones at link set-up, the next full update comes about 600 s after start-up, not 120 s, and `N BC T` shows a "Next Full Update" in the past.
4. Remove INPBCINTERVAL and restart: `N BC T` shows 3600.

## Versions

505a, 505c and 505o.

## Reported

Reported on the xrouter group on 2026-10-11. The first report said full updates were never re-sent; that was corrected the same day (the observation run was shorter than 10 minutes).

## Tests

- `test_xrouter_refreshes_rif_on_schedule`
- `test_xrouter_refreshes_rif_to_xnet`
- `test_xrouter_refreshes_rif_to_tnn`
- `test_xrouter_refreshes_rif_to_xrpeer`
- `test_xrpeer_refreshes_rif_on_schedule` (the same behaviour in the second XRouter)
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#2-xrouter-ignores-inpbcinterval-it-re-sends-its-routes-only-every-10-minutes

Status: open.
