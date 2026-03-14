# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Meeting Scribe** is a real-time meeting transcription and analysis system combining Python backend audio/AI processing with a TypeScript Obsidian plugin frontend. It captures audio, transcribes via Whisper, identifies speakers with pyannote.audio, and analyzes via local Ollama models with optional Claude API escalation.

**Current Phase**: 4.5 — Assistant integration with topic detection and vault organization
**Version**: 0.2.0
**Architecture**: Dual-stream processing (real-time transcript + batched AI analysis)

## Quick Start Commands

### Backend (Python Server)
```bash
cd server
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run server
python -m src.main

# Run tests
pytest tests/

# Run specific test
pytest tests/test_skills.py
```

### Frontend (TypeScript Plugin)
```bash
cd obsidian-plugin
npm install

# Development (watch mode with sourcemaps)
npm run dev

# Production build
npm run build
```

### Configuration
- Server: `server/config.toml` (copy from `config.example.toml`)
- Plugin: Settings tab in Obsidian (server URL, vault folder, model selection)

---

## Core Architecture

### Dual-Stream Processing Pipeline

The system is built around **two independent processing streams**:

**Stream 1 (Real-time)**: Audio → Faster-Whisper → WebSocket broadcast to Obsidian
- Every transcription chunk is immediately sent to the plugin
- Provides low-latency transcript display
- Happens in `src/pipeline.py` → `src/transcriber.py`

**Stream 2 (Batched Analysis)**: Accumulated segments → Ollama assistant → analysis → vault management
- Segments accumulate in 2-5 minute overlapping windows (30-60s overlap for context)
- Ollama model analyzes every ~3 minutes
- Generates summaries, extracts action items, detects topics
- Happens in `src/assistant.py` → `src/ollama_client.py`
- Results flow through `src/vault_manager.py` to create/update notes

### Key Architectural Components

| Module | Purpose | Dependencies |
|--------|---------|--------------|
| `src/main.py` | Entry point, CLI parsing, pipeline orchestration | All others |
| `src/pipeline.py` | Main orchestrator connecting all streams | transcriber, diarizer, ws_server, assistant |
| `src/transcriber.py` | faster-whisper integration | numpy |
| `src/audio_capture.py` | sounddevice microphone input | sounddevice, numpy |
| `src/diarizer.py` | pyannote.audio speaker identification | pyannote.audio |
| `src/assistant.py` | Ollama integration + analysis logic (summaries, action items, topics) | ollama_client, models |
| `src/ws_server.py` | WebSocket server for real-time plugin communication | websockets |
| `src/vault_manager.py` | Markdown file I/O to Obsidian vault | pathlib |
| `src/skills.py` | Skills system loader (markdown-based behavioral instructions) | yaml, pathlib |
| `src/models.py` | Shared TypeScript and Python data models (Segment, TranscriptionResult, etc.) | dataclasses |

### WebSocket Protocol (Server → Plugin)

Key message types (`models.py`):
- `transcription_segment`: Real-time transcript chunks with speaker info
- `assistant_summary`: Rolling meeting summaries from Ollama
- `assistant_action_items`: Extracted action items with assignees
- `assistant_topic_change`: New topic detected with start time and segments
- `speaker_diarized`: Speaker identification updates

### Vault Organization Logic

When assistant analysis occurs, it automatically manages Obsidian vault files:

```
{vault-root}/
├── meetings/YYYY-MM-DD-minutes.md       # Appended per session (never duplicated)
├── topics/{topic-slug}.md                # One per topic, progressively refined
├── action-items.md                       # Running tracker of all action items
└── _assistant/                           # Assistant's workspace
    ├── context.md                        # Accumulated memory
    └── skills/                           # Markdown files with behavioral instructions
```

**Critical detail**: Daily minutes file is **appended** if it already exists for that date (supports multiple sessions per day). Topics accumulate and are progressively refined on subsequent references.

---

## Technology Stack

### Backend
- **Python 3.11+** (requires 3.11+ for type hints)
- **faster-whisper**: Speech-to-text (optimized Whisper implementation)
- **pyannote.audio 3.1+**: Speaker diarization (requires HuggingFace model access)
- **websockets 12+**: WebSocket server for real-time communication
- **aiohttp 3.9+**: HTTP client (async) for Ollama API calls
- **sounddevice 0.4.6+**: Microphone audio capture
- **numpy 1.24+**: Numerical operations for audio processing
- **asyncio**: Core async runtime

**Why async throughout?**: Real-time audio capture + WebSocket broadcasting + Ollama API calls all run concurrently without blocking each other.

### Frontend
- **TypeScript 5.3**: Obsidian plugin source code
- **Obsidian API**: Plugin lifecycle, vault I/O, UI components (only dev dependency)
- **esbuild 0.20**: Fast bundler for plugin
- **ESLint + @typescript-eslint**: Code quality

### External Services
- **Ollama** (local): Runs language models (Phi-4-mini, Qwen3 recommended)
- **Claude API** (optional): Frontier model for end-of-session synthesis (not yet integrated)
- **HuggingFace** (optional): Token for downloading speaker diarization models

---

## Design Patterns & Critical Decisions

### 1. Assistant as Pipeline Stage (Not Sidecar)
The assistant runs **inside** `src/pipeline.py`, not as a separate service. This means:
- **Pro**: Shared segment buffer, same event loop, simpler deployment
- **Con**: Can't scale assistant independently; blocks if Ollama is slow
- **Implication**: Don't add expensive blocking I/O in the assistant path without moving to a sidecar

### 2. Skills System as Markdown Files
Behavioral instructions are stored as YAML frontmatter + markdown in `{vault}/_assistant/skills/`:
```markdown
---
type: skill
created: 2026-03-09
source: manual | generated
confidence: 0.8
---
# Skill Name
## When to use
[context]
## Instructions
[behavior]
```
The assistant learns from these progressively. This is **not yet** auto-generated; currently it's manual.

### 3. Overlapping Batches for Context Continuity
Analysis runs on **overlapping 2-5 minute windows** (default 30-60s overlap) to maintain context. This allows the assistant to remember what was just discussed while processing new segments.

### 4. Speaker Diarization + Renaming
`src/diarizer.py` identifies speakers automatically. Speaker names are **session-scoped** and stored in `.meeting-scribe.json` in the vault root. They don't persist across sessions—by design, to avoid stale labels.

---

## Key Files & Modification Patterns

### Common Changes

| Task | Files to Edit | Notes |
|------|---------------|-------|
| Add new Ollama model | `src/assistant.py` model selection logic | Update model list in plugin settings UI too |
| Change analysis cadence (2-5 min window) | `src/pipeline.py` accumulator settings | Also update overlap logic |
| Add new WebSocket message type | `src/models.py` + `src/pipeline.py` + plugin `types.ts` + `main.ts` | Keep plugin and server message types in sync |
| Modify vault folder structure | `src/vault_manager.py` file paths | Update README vault diagram and design doc |
| Change speaker diarization | `src/diarizer.py` + `src/pipeline.py` speaker assignment | Verify impact on transcript display |
| Add new assistant output (e.g., topic tags) | `src/assistant.py` + WebSocket message types + plugin UI + vault manager | Multi-file coordination required |

### Testing Patterns

- **Unit tests** in `tests/` run offline (no Ollama, no audio)
- **Integration tests** (test_pipeline.py) require Ollama running and network access
- Use `pytest -k <test_name>` to run specific tests
- Skills tests (`test_skills.py`) and topic detection (`test_topic_detection.py`) are key for assistant behavior

### File Structure

```
server/
├── src/
│   ├── main.py                 # Entry, CLI args, signal handling
│   ├── pipeline.py             # Core orchestrator (Stream 1 + 2)
│   ├── transcriber.py          # Whisper integration
│   ├── audio_capture.py        # Microphone input
│   ├── diarizer.py             # Speaker identification
│   ├── ws_server.py            # WebSocket broadcast
│   ├── assistant.py            # Ollama + analysis logic (★ main logic)
│   ├── ollama_client.py        # Ollama API client
│   ├── vault_manager.py        # File I/O to Obsidian
│   ├── skills.py               # Skills loader
│   ├── models.py               # Data models (sync with plugin types.ts)
│   └── __init__.py
├── tests/                       # Unit + integration tests
├── pyproject.toml              # Dependencies, build config
└── config.example.toml         # Default config template

obsidian-plugin/
├── src/
│   ├── main.ts                 # Plugin lifecycle + WebSocket connection (★ entry)
│   ├── ws-client.ts            # WebSocket client wrapper
│   ├── transcript-view.ts      # Live transcript UI component
│   ├── types.ts                # TypeScript models (sync with Python models.py)
│   ├── settings.ts             # Plugin settings UI
│   ├── vault-manager.ts        # Vault file operations
│   ├── speaker-store.ts        # Session speaker persistence
│   ├── markdown-writer.ts      # Markdown generation utilities
│   └── __init__.ts (if exists)
├── package.json                # Dependencies, build scripts
├── esbuild.config.mjs          # Bundler config
└── main.js                     # Compiled output (git-ignored)
```

---

## Important Implementation Details

### Model Selection & Performance
- **Phi-4-mini** (2.5GB): Best for structured output and reasoning (recommended for most use cases)
- **Qwen3 4B** (2.5GB): Larger context window (256K) for long sessions
- **M2 Max 32GB**: Budget ~4-5GB VRAM for assistant models, leaving headroom for Whisper + pyannote (~1-2GB each)

### Async I/O Patterns
- All network I/O (WebSocket, Ollama API, vault I/O) is async via `asyncio`
- Audio capture runs in a thread pool to avoid blocking the event loop
- Don't use blocking I/O in the main pipeline without moving to thread pool

### Configuration Management
- `config.toml` is loaded at startup (see `main.py`)
- Key settings:
  - `server.port`: WebSocket listen port (default 8000)
  - `assistant.window_size_seconds`: Analysis batch size (default 180 = 3 min)
  - `assistant.overlap_seconds`: Context overlap (default 30)
  - `ollama.base_url`: Ollama service endpoint
  - `vault.root`: Obsidian vault directory

### Error Handling
- Transcription failures are **non-fatal** (server keeps running)
- Diarization fallback: If speaker ID fails, segments are labeled "Unknown"
- Ollama unavailability: Assistant gracefully skips analysis, error logged
- WebSocket disconnects: Plugin reconnects automatically

---

## Testing Strategy

### Running Tests
```bash
cd server
pytest tests/                    # All tests
pytest tests/ -v                 # Verbose
pytest tests/test_skills.py      # Single file
pytest -k "topic_detection"      # Pattern match
```

### Key Test Files
- **test_skills.py**: Skills loader, YAML parsing, skill matching
- **test_topic_detection.py**: Topic detection accuracy and segmentation
- **test_assistant.py**: Ollama integration, message formatting
- **test_pipeline.py**: End-to-end dual-stream processing (requires Ollama)

### What's Tested
- ✅ Transcriber (offline, using sample audio files)
- ✅ Diarizer (offline, using synthetic segments)
- ✅ Skills loading and parsing
- ✅ WebSocket message formatting
- ✅ Vault file path construction
- ⚠️ Ollama API calls (integration tests, require running Ollama)

---

## Known Limitations & Gotchas

### 1. Diarization Model Setup
- Requires HuggingFace token for model download (first run)
- Stored in `~/.huggingface/token` after first run
- Long wait on first execution while model downloads (~1GB)

### 2. Ollama Model Availability
- If Ollama isn't running or model isn't available, assistant silently skips analysis
- Check logs for Ollama errors; don't assume silent failures are normal
- Call `ollama pull phi4-mini` or `ollama pull qwen3:4b` to preload models

### 3. Context Window Limits
- Phi-4-mini: 128K context (good for 2-3 hour meetings)
- Qwen3 4B: 256K context (better for 4+ hour sessions)
- Longer sessions benefit from Claude API synthesis (not yet implemented)

### 4. Speaker Names are Session-Scoped
- Renamed speakers (via plugin UI) only persist in `.meeting-scribe.json` for current session
- Use vault notes to create persistent speaker profiles
- By design: avoids stale labels across different contexts

### 5. Plugin ↔ Server Model Sync
- Changes to `models.py` require corresponding updates to `types.ts`
- WebSocket messages must match on both sides
- Easy to miss: forgetting to update one side after model changes

### 6. Async Audio Capture
- Microphone input runs in thread pool (blocking syscall)
- Thread pool exhaustion would block transcription; not a practical issue on M1+ Macs
- Watch for: if adding other blocking I/O, move to separate thread pool

---

## Development Workflow

### Adding a New Feature (Example: Topic Tags)

1. **Define data model**:
   - Add `AssistantTopicTags` to `models.py`
   - Add corresponding TypeScript type to `types.ts`

2. **Server-side logic**:
   - Extend `assistant.py` analysis to generate tags
   - Add WebSocket message broadcast in `pipeline.py`

3. **Plugin UI**:
   - Display tags in `transcript-view.ts`
   - Serialize tags to markdown in `markdown-writer.ts`

4. **Vault storage**:
   - Add tag metadata to note files in `vault_manager.py`

5. **Test**:
   - Add unit test for tag generation in `test_assistant.py`
   - Manually verify end-to-end in Obsidian

### Debugging Tips

- **Server logs**: Run with `python -m src.main` to see all output
- **Plugin logs**: Obsidian console (Cmd+Shift+I on Mac)
- **WebSocket messages**: Log in `ws_server.py` or `main.ts`
- **Ollama issues**: `curl http://localhost:11434/api/tags` to list models
- **Vault file issues**: Check permissions, use absolute paths in config

---

## References

- **README.md**: User-facing documentation, quick start, troubleshooting
- **docs/plans/2026-03-09-assistant-integration-design.md**: Detailed architecture, sprint plans, model strategy
- **pyproject.toml**: Python dependencies, version pinning
- **package.json**: TypeScript plugin dependencies
- **.github/workflows/**: Claude Code review integration (reads PR context)

---

## Project Status & Upcoming Work

**Current Focus**: Phase 4.5 — Assistant integration (rolling summaries, action items, topic detection)

**Completed**:
- ✅ Real-time transcription (Stream 1)
- ✅ Speaker diarization
- ✅ Plugin UI (transcript display, speaker renaming)
- ✅ Obsidian vault integration

**In Progress**:
- 🔄 Assistant pipeline with Ollama models
- 🔄 Rolling summaries (every ~3 minutes)
- 🔄 Action item extraction
- 🔄 Topic detection and segmentation

**Planned**:
- [ ] Claude API escalation for complex synthesis
- [ ] Progressive idea refinement across sessions
- [ ] Embedding-based topic matching
- [ ] Multi-language support
