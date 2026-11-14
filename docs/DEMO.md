# Local demonstration

1. Start the backend and frontend using the root README. Open the interface.
2. Choose “Use development example” (2026-11-20T00:00:00Z), original R01, 24h, geometric horizon, 5-minute spacing and no future search. This date is a development example, not a mission choice.
3. Run comparison. Inspect original R01/R04 and delayed R01/R04 (2026-11-27T00:00:00Z). The recorded real-source example found 1,440 modeled shared minutes for all four and KEEP_SITE_AFTER_DELAY. Another input may produce a different result or insufficient data.
4. Select delayed R04. Inspect elevation lines, 0° threshold, shared timeline, waiting time and the unknown fraction. Move the sky time slider. Download CSV.
5. Select a map cell. Read its immutable ID and unevaluated-center status. Select the reference-point scatter marker to highlight the containing cell; this does not evaluate its center.
6. Open “How calculated” to inspect JPL request URLs, raw hashes, reference-sphere height and limits.
7. Change to LOCAL_TERRAIN and rerun. Without a complete verified horizon the result must be INSUFFICIENT_DATA, not geometric fallback.

For a short offline presentation, set `VITE_USE_MOCKS=true`, restart Vite and choose any of the six synthetic outcomes. Keep the visible synthetic banner in screenshots and recordings.
