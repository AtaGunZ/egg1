# web UI

No build step: vanilla ES modules + importmap, three.js vendored in `vendor/three`. Open `http://127.0.0.1:8765/`.
Modules: `viewer.js` (3D, storeys/section/classes/ghost/highlight/dims/picking), `review.js` (list + decision form),
`settings.js` (context + rule thresholds), `drawing2d.js` (SVG drawing), `app.js` (wiring, WS live updates).
Shortcuts: arrows move, A/W/C/N decide, U next undecided, F fit, H/I/R hide/isolate/reset, S settings, Esc deselect.
