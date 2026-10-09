# Legacy comparison screens (flowchart stages D–H)

These are the screens of the earlier "MRM Royalty Comparison" module (6% benchmark comparison, IPRS enquiry packs,
cases). They are kept for reference but are **not part of the build** (`tsconfig.json` includes `src/` only).
The matching API is mounted under `/api/compare` only when `LEGACY_COMPARISON=true`.
To revive them, move this folder back under `src/` and point their API calls at `/api/compare/...`.
