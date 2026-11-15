# Web renderer — run in a browser, no engine, no build step

Displays your Python sim + AI in a browser canvas. Python runs the game; the web
page polls it and draws. Nothing to install on the web side.

## Run it (two steps)

1. Start the sim server in a terminal:
   ```bash
   cd devhacks-2026-0xAI
   python3 state_server.py          # serves http://127.0.0.1:8765
   ```
2. Open `web/index.html` in a browser.
   - Simplest: double-click the file, or drag it into Chrome.
   - If the browser blocks the local fetch (some setups), serve the folder:
     ```bash
     cd web && python3 -m http.server 8000
     ```
     then open http://127.0.0.1:8000

You'll see the map, champions (blue ally / red enemy) moving with HP bars,
minions, the dragon, attack/cast effect lines, and a right-hand panel showing
**each champion's current AI behavior** live. Use the scenario dropdown to switch
(balanced 5v5, dive, teamfight, etc.) — it resets the sim on the server.

## Why this instead of Unity
Same AI, zero rewrite, nothing to install or learn, and it's shareable by a link
or a screen recording — ideal for the 3-minute demo video. The server
(`state_server.py`) is the single source of truth; the browser is a pure display.

## Record a clean demo
Pick `balanced`, let a teamfight play out, screen-record the canvas + AI panel.
The behavior labels updating live is the shot that shows the AI is actually
reasoning, not scripted.
