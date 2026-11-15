// SimRenderer.cs — the ONLY script you need in Unity.
//
// It polls the Python state server (http://127.0.0.1:8765/state) each frame,
// parses the world JSON, and renders champions + minions as sprites that move
// smoothly. Unity does NO game logic — it's a pure display of your Python sim.
//
// SETUP: see unity/UNITY_SETUP.md. In short: new 2D project, create an empty
// GameObject, attach this script, press Play with state_server.py running.
//
// Requires Unity 2021+ (uses UnityWebRequest + JsonUtility, both built in).

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

public class SimRenderer : MonoBehaviour
{
    [Header("Server")]
    public string stateUrl = "http://127.0.0.1:8765/state";
    public float pollInterval = 0.1f;      // seconds between polls (10 Hz = sim tick)

    [Header("World scaling")]
    public float mapSize = 15000f;         // matches Python MAP_SIZE
    public float worldToUnity = 0.004f;    // 15000 units -> 60 Unity units wide

    [Header("Look")]
    public float moveLerp = 0.25f;         // smoothing (0..1); higher = snappier

    // ---- JSON data classes (shapes mirror state_server.py snapshot) ----
    [System.Serializable] public class Champ {
        public string name, team, role, behavior;
        public float x, y, hp, max_hp, hp_frac, mp_frac, cc, dead_timer;
        public int level; public bool alive;
    }
    [System.Serializable] public class Minion {
        public string team, kind; public float x, y, hp_frac;
    }
    [System.Serializable] public class Obj {
        public string name; public float x, y, spawns_in; public bool up;
    }
    [System.Serializable] public class Snapshot {
        public float time, map_size; public string desc;
        public Obj objective; public Champ[] champions; public Minion[] minions;
    }

    private readonly Dictionary<string, GameObject> champObjs = new();
    private readonly List<GameObject> minionPool = new();
    private GameObject objectiveObj;

    void Start() { StartCoroutine(PollLoop()); }

    IEnumerator PollLoop()
    {
        while (true)
        {
            using (var req = UnityWebRequest.Get(stateUrl))
            {
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                    Render(JsonUtility.FromJson<Snapshot>(req.downloadHandler.text));
            }
            yield return new WaitForSeconds(pollInterval);
        }
    }

    Vector3 ToWorld(float x, float y)
    {
        // center the map at origin so the camera framing is easy
        float half = mapSize * worldToUnity * 0.5f;
        return new Vector3(x * worldToUnity - half, y * worldToUnity - half, 0);
    }

    void Render(Snapshot s)
    {
        if (s == null) return;

        // objective marker
        if (objectiveObj == null)
            objectiveObj = MakeDot("OBJECTIVE", new Color(0.8f, 0.6f, 0.2f), 1.4f);
        objectiveObj.transform.position = ToWorld(s.objective.x, s.objective.y);
        objectiveObj.SetActive(true);

        // champions
        var seen = new HashSet<string>();
        if (s.champions != null) foreach (var c in s.champions)
        {
            seen.Add(c.name);
            if (!champObjs.TryGetValue(c.name, out var go))
            {
                Color col = c.team == "ALLY" ? new Color(0.3f, 0.6f, 1f)
                                             : new Color(0.9f, 0.3f, 0.3f);
                go = MakeDot(c.name, col, 1.0f);
                champObjs[c.name] = go;
            }
            go.SetActive(c.alive);
            if (c.alive)
            {
                Vector3 target = ToWorld(c.x, c.y);
                go.transform.position = Vector3.Lerp(go.transform.position,
                                                     target, moveLerp);
            }
        }

        // minions: simple pooled dots
        int idx = 0;
        if (s.minions != null) foreach (var m in s.minions)
        {
            GameObject md;
            if (idx < minionPool.Count) md = minionPool[idx];
            else { md = MakeDot("m", Color.white, 0.3f); minionPool.Add(md); }
            Color mc = m.team == "ALLY" ? new Color(0.4f, 0.55f, 0.9f)
                                        : new Color(0.9f, 0.45f, 0.45f);
            md.GetComponent<SpriteRenderer>().color = mc;
            md.transform.position = ToWorld(m.x, m.y);
            md.SetActive(true);
            idx++;
        }
        for (int i = idx; i < minionPool.Count; i++) minionPool[i].SetActive(false);
    }

    // create a simple circle sprite GameObject at runtime (no assets needed)
    GameObject MakeDot(string name, Color color, float scale)
    {
        var go = new GameObject(name);
        var sr = go.AddComponent<SpriteRenderer>();
        sr.sprite = CircleSprite();
        sr.color = color;
        go.transform.localScale = Vector3.one * scale;
        return go;
    }

    static Sprite _circle;
    static Sprite CircleSprite()
    {
        if (_circle != null) return _circle;
        int d = 32; var tex = new Texture2D(d, d);
        float r = d / 2f;
        for (int y = 0; y < d; y++)
            for (int x = 0; x < d; x++)
            {
                float dx = x - r + 0.5f, dy = y - r + 0.5f;
                bool inside = dx * dx + dy * dy <= r * r;
                tex.SetPixel(x, y, inside ? Color.white : Color.clear);
            }
        tex.Apply();
        _circle = Sprite.Create(tex, new Rect(0, 0, d, d), new Vector2(.5f, .5f), d);
        return _circle;
    }
}
