# Meeting Scribe Test Plan — Thomas + Hoyt Session

## Pre-flight Setup (one-time, ~10 min)

### 1. Pull an assistant model into Ollama

You don't have phi4-mini or qwen3:4b yet. Pick one:

```bash
# Option A: phi4-mini (3.8B, 128K context, fast reasoning) — RECOMMENDED
ollama pull phi4-mini

# Option B: qwen3 4B (256K context, better for marathon sessions)
ollama pull qwen3:4b

# Option C: skip the pull, use gemma3:1b (already installed, but weaker)
# just pass --assistant-model gemma3:1b when starting the server
```

Quick sanity check after pulling:
```bash
ollama run phi4-mini "Say hello in exactly 5 words"
# Should respond fast with a 5-word greeting
```

### 2. Set up the Python environment

```bash
cd ~/projects/meeting-scribe-sprint1/server

# Create venv and install everything
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# If faster-whisper gives you trouble on M2:
# uv pip install faster-whisper --no-build-isolation
```

### 3. Check your mic

```bash
source .venv/bin/activate
python3 -c "
import sounddevice as sd
print(sd.query_devices())
print()
print('Default input:', sd.default.device[0])
"
```

Note the device index if you want a specific mic (e.g., external USB mic).
If using MacBook built-in mic, the default is usually fine.

### 4. Build the Obsidian plugin

```bash
cd ~/projects/meeting-scribe-sprint1/obsidian-plugin
npm install
npm run build
```

Then symlink it into your Obsidian vault:
```bash
# Find your vault path (replace with actual vault name)
VAULT_PATH="$HOME/path/to/your/vault"
mkdir -p "$VAULT_PATH/.obsidian/plugins/meeting-scribe"
cp main.js manifest.json styles.css "$VAULT_PATH/.obsidian/plugins/meeting-scribe/"
```

Restart Obsidian, go to Settings → Community Plugins → Enable "Meeting Scribe".

---

## Test Session (~30 min with Hoyt)

### Step 1: Start the server

```bash
cd ~/projects/meeting-scribe-sprint1/server
source .venv/bin/activate

# Basic start (assistant auto-detects model)
python3 -m src.main --model base --host 0.0.0.0

# OR with explicit options:
python3 -m src.main \
  --model base \
  --host 0.0.0.0 \
  --port 9876 \
  --chunk-duration 30 \
  --assistant-model phi4-mini \
  --assistant-window 180

# OR to test WITHOUT assistant (baseline transcription only):
python3 -m src.main --model base --host 0.0.0.0 --no-assistant
```

**Watch the console for:**
- `Ollama ready — using model: phi4-mini` (or whichever model)
- `Assistant initialized — dual-stream active`
- `WebSocket server started on 0.0.0.0:9876`
- `Pipeline running — waiting for 'start' command`

If you see `Assistant unavailable — single-stream mode`, Ollama isn't reachable or no preferred model found.

### Step 2: Connect from Obsidian

1. Open Obsidian
2. Click the 🎤 mic icon in the ribbon (left sidebar)
3. The transcript view opens in the right panel
4. Use command palette: `Meeting Scribe: Start Meeting`
5. You should see "Connected" status in the transcript view

### Step 3: Talk with Hoyt (~15-20 min)

Have a real conversation. Good test topics:
- **D&D campaign planning** — natural topic for you two, generates action items
- **Feature ideas for the crawler** — tests if the assistant catches "we should do X" patterns
- **Decisions** — "let's go with approach A" should show up as action items

**What to watch in the server console:**
- Segments appearing every 30 seconds (that's your chunk duration)
- After ~3 minutes: `Analysis #1: N segments (0.0–180.0s)` — the assistant is working
- `Summary broadcast: ...` — summary sent to the plugin
- `Action items broadcast: N items` — action items extracted

**What to watch in Obsidian:**
- Live transcript appearing with speaker labels
- After diarization runs: speakers get labeled (SPEAKER_00, SPEAKER_01)
- Click a speaker label to rename it ("Thomas", "Hoyt")

### Step 4: Stop and review

1. Command palette: `Meeting Scribe: Stop Meeting`
2. Final diarization runs
3. Transcript saved to your vault's `Meetings/` folder
4. Check the markdown file — it should have all segments with speaker names

---

## What to Validate

### Transcription (Stream 1 — existing)
- [ ] Audio captures from your mic
- [ ] Segments appear in Obsidian within ~30s
- [ ] Text is reasonable (doesn't need to be perfect)
- [ ] Diarization assigns different speaker IDs to you vs Hoyt
- [ ] Renaming speakers works and persists

### Assistant (Stream 2 — new)
- [ ] Server logs show `Analysis #1`, `#2`, etc. every ~3 minutes
- [ ] Summaries appear in server logs and make sense
- [ ] Action items appear when someone says "we should...", "let's...", "I'll..."
- [ ] Assistant doesn't crash or block the transcript stream
- [ ] Summary builds on previous summary (rolling context)

### Resilience
- [ ] Long pauses in conversation don't crash anything
- [ ] If Ollama is slow, transcription still flows normally (async)
- [ ] Plugin reconnects if you briefly lose connection

---

## Quick Smoke Test (no Hoyt needed, 2 min)

If you just want to verify the plumbing works before the real session:

```bash
cd ~/projects/meeting-scribe-sprint1/server
source .venv/bin/activate

# Terminal 1: Start server
python3 -m src.main --model tiny --chunk-duration 10 --assistant-window 30

# Terminal 2: Connect with wscat (or just use Obsidian)
# brew install wscat  (if needed)
wscat -c ws://localhost:9876

# In wscat, send:
{"type":"start"}

# Talk for ~30 seconds, watch segments appear
# After ~30s the assistant should fire its first analysis
# Then stop:
{"type":"stop"}
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'faster_whisper'` | `source .venv/bin/activate` — you're not in the venv |
| `Assistant unavailable` | Check `ollama list` — need phi4-mini or qwen3:4b |
| No audio captured | Check `--device N` flag, or check System Preferences → Sound → Input |
| Plugin not showing in Obsidian | Rebuild plugin, check symlink path, restart Obsidian |
| `OSError: [Errno -9996]` | Another app has the mic. Close Zoom/Discord/etc. |
| Segments appear but no assistant output | Check `--assistant-window` — default is 180s (3 min). Lower it for testing: `--assistant-window 30` |
| Ollama responses very slow | gemma3:1b is faster but less capable. Or try `--assistant-window 300` for less frequent analysis |
