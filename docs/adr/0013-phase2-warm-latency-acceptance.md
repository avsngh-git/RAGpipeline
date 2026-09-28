---
status: accepted
date: 2026-09-28
---

# Set the Phase 2 warm-latency acceptance limit to 2,000 ms

The v10 assessment measured warm p95 at 1,602.2 ms against its then-frozen 1,500 ms limit. The owner judged 1.6 seconds reasonable and directed that Phase 2 tolerate longer interactive searches while remaining far below the existing 30-second per-request deadline. Therefore the fresh R8 acceptance-v10 protocol sets maximum warm p95 to 2,000 ms; all other gates and prior assessment outcomes remain unchanged.
