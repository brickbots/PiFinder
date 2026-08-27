# The UBX parser yields markers for frames it cannot decode

`UBXParser.parse_messages` used to yield only frames it successfully decoded: an unregistered class/id became `{"error": "Unknown message type"}` and was dropped by the `if "class" in parsed` guard, and a checksum failure was logged at WARNING and dropped. Nothing above the parser could tell "no bytes arriving" from "bytes arriving that we don't understand" — which made a receiver talking an unexpected dialect, or running at the wrong baud rate, look pixel-identical to an unplugged GPS. The parser now yields a **marker** for both cases (`{"class": "?XXYY"}` naming the two message bytes, `{"class": "?CKSUM"}` for a checksum mismatch), widening its output contract from *messages* to *events*.

## Considered options

- **A stats dict on the parser instance.** Keeps the yield contract untouched, but `process_messages` receives `parser.parse_messages` as a bare bound method and never sees the parser object, so exposing counters means changing the signature at both call sites (`gps_ubx`, `gps_fake`) plus the dispatch tests — more churn than the thing it was avoiding, in exchange for a second, parallel egress path for the same information.
- **A separate counter argument threaded through `process_messages`.** Same churn, and it splits "what arrived" across two mechanisms that have to be kept in step.
- **Leave it alone and infer from silence.** Rejected because silence is precisely the ambiguity being removed.

## Consequences

Anything consuming the parser's output must tolerate a `class` that is not a real message type. Today that is only `process_messages`, whose `elif` chain ignores unrecognised classes harmlessly, so no dispatch behaviour changes — but the guard is now "is this a class I handle", not "is this a message". The `?` prefix is reserved for markers and must not be used by any real message class.

The **comms row** on the STATUS screen is the only consumer that reads markers, and it is what makes the distinction visible: a churning `?CKSUM` says bytes are arriving corrupted, a churning `?0135` says the receiver is emitting something we have no parser for, and a frozen name with a rising age says the link is gone.

A resync storm can yield markers far faster than real messages arrive, so the publisher caps how often it forwards events onto `gps_queue`; the cap is a rate limit on *reporting*, not on parsing. Only the event's name is forwarded — the main process stamps arrival with its own monotonic clock, because that is the process the row renders in and `time.monotonic()` is not comparable across processes.
