# Unity renderer — step-by-step (for a first-time Unity user)

Unity here is **only a display** for your Python sim. Python runs the game and
AI; Unity polls it and draws moving sprites. You do NOT build game logic in
Unity. This guide gets colored dots moving in Unity, driven by your sim, in
about 30 minutes. Sprites/map/polish come after that works.

## 0. What you need
- Your Python sim running the state server (see step 2).
- Unity installed (step 1).

## 1. Install Unity (~15 min, one time)
1. Download **Unity Hub** from unity.com/download. Install it.
2. In Unity Hub → **Installs → Install Editor** → pick the latest **LTS** version
   (e.g. 2022.3 LTS). Accept defaults. (Big download; let it finish.)
3. Hub → **Projects → New Project** → template **2D (Core)** → name it
   `sim-renderer` → Create.

## 2. Start the Python state server (in a terminal)
```bash
cd devhacks-2026-0xAI
SCENARIO=balanced python3 state_server.py
```
You should see: `-> http://127.0.0.1:8765/state`. Leave it running.
Test it in a browser: open http://127.0.0.1:8765/state — you should see JSON.

## 3. Add the renderer script (~5 min)
1. In Unity's **Project** window (bottom), right-click `Assets` →
   **Create → Folder** → name it `Scripts`.
2. Right-click `Scripts` → **Create → C# Script** → name it exactly
   **`SimRenderer`** (must match the class name).
3. Double-click it to open, **delete everything**, and paste the full contents
   of `unity/SimRenderer.cs` from the repo. Save.

## 4. Put it in the scene (~2 min)
1. In the **Hierarchy** window (left), right-click → **Create Empty**. Name it
   `Sim`.
2. Select `Sim`. In the **Inspector** (right), click **Add Component** → type
   `SimRenderer` → select it. (If it doesn't appear, the file name/class name
   don't match — fix that.)
3. The script's fields show in the Inspector (Server URL, scaling). Leave
   defaults.

## 5. Frame the camera (~2 min)
1. Select **Main Camera** in the Hierarchy.
2. In the Inspector set **Projection = Orthographic** (it is by default in 2D),
   and **Size = 35** (so the ~60-wide map fits). Position (0, 0, -10).

## 6. Press Play
Hit the **▶ Play** button at the top. With the server running you should see
blue (ally) and red (enemy) dots moving, plus small minion dots and a gold
objective marker. **That's your Python sim rendering in Unity.**

## Troubleshooting
- **Nothing shows / errors about connection:** the server isn't running, or the
  URL is wrong. Confirm http://127.0.0.1:8765/state loads in a browser.
- **"JsonUtility" errors:** make sure you pasted the whole script unchanged.
- **Dots off-screen:** raise/lower Camera **Size**, or tweak `worldToUnity` on
  the Sim component.
- **macOS blocks the request:** Unity may need "Allow" on first network use;
  also ensure the server prints the `/state` line.

## What's next (once dots move)
Tell me it works and we add, in order:
1. real sprites (your Kenney pack) instead of circles,
2. a Rift background image,
3. HP bars + the behavior label over each champion,
4. attack/cast effect lines (the server already sends `fx`).

Each is a small, additive change to this one script — I'll give you the exact
code and you paste it in.
```
