# Meeting Scribe

Real-time meeting transcription, analysis, and organization with local AI assistant.

**Status**: Phase 4.5 — Assistant integration with topic detection and vault organization

## Features

- **Real-time transcription**: Capture and transcribe meetings as they happen using faster-whisper
- **Speaker diarization**: Automatically identify and label speakers with pyannote.audio
- **Live transcript view**: Obsidian plugin with inline speaker renaming
- **AI assistant analysis**: Local Ollama models (Phi-4-mini, Qwen3) for:
  - Rolling meeting summaries (updated every ~3 minutes)
  - Action item extraction
  - Topic detection and segmentation
  - Progressive idea refinement
- **Automated vault organization**:
  - Daily meeting minutes (never duplicated, supports multiple sessions per day)
  - Topic notes with persistent refinement
  - Action item tracker
  - Assistant workspace with skills and context
- **Skills system**: Markdown-based behavioral instructions for customizing assistant behavior
- **Plugin UI**: Color-coded controls, status indicators, live timer, assistant panel

## Quick Start

### Prerequisites
- Python 3.9+
- Node.js 16+ (for Obsidian plugin)
- Ollama (with Phi-4-mini or Qwen3 models)
- Obsidian 1.5+

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/WastelandWares/meeting-scribe.git
   cd meeting-scribe
   ```

2. **Set up Python environment**
   ```bash
   cd server
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -e .
   ```

3. **Install Obsidian plugin**
   ```bash
   cd ../obsidian-plugin
   npm install
   npm run dev  # For development
   npm run build  # For production
   ```

4. **Configure server**
   ```bash
   cp server/config.example.toml server/config.toml
   # Edit config.toml to set your preferences
   ```

5. **Start the server**
   ```bash
   cd server
   python -m src.main
   ```

6. **Enable plugin in Obsidian**
   - Open Obsidian settings → Community plugins
   - Enable "Meeting Scribe"
   - Configure vault folder and server URL in plugin settings

## Architecture

```
Audio Input
    ↓
faster-whisper (STT)
    ├─→ Stream 1: Real-time transcript → Obsidian Plugin
    └─→ Stream 2: Batched segments → Assistant (Ollama)
                       ↓
                 Topic Detection
                 Summary Generation
                 Action Item Extraction
                       ↓
                 Vault Manager → Obsidian Notes
                       ↓
                 WebSocket → Plugin UI
```

### Processing Streams

- **Stream 1 (Real-time)**: Every transcription chunk → immediate broadcast to plugin
- **Stream 2 (Assistant)**: Overlapping 2-5 minute windows → analysis every ~3 minutes

### Model Strategy

| Model | Size | Context | Best For |
|-------|------|---------|----------|
| **Phi-4-mini** | 2.5GB | 128K | Reasoning, tool calling, structured output |
| **Qwen3 4B** | 2.5GB | 256K | Long sessions (4+ hours), large context |
| **Granite 3.1 2B** | 1.6GB | 4K | Fastest option, limited context |

## Vault Organization

When the assistant runs, it organizes notes in your Obsidian vault:

```
{vault-root}/
├── meetings/
│   ├── 2026-03-12-minutes.md    # Daily file, appended per session
│   └── 2026-03-11-minutes.md
├── topics/
│   ├── voice-identification.md   # One note per topic, progressively refined
│   ├── architecture.md
│   └── deployment.md
├── action-items.md               # Running tracker of all action items
└── _assistant/                   # Assistant workspace
    ├── context.md                # Accumulated context and memory
    └── skills/                   # Customizable behavior
        ├── summarizer.md
        └── action-tracker.md
```

## Configuration

### Server (config.toml)

```toml
[server]
host = "localhost"
port = 8000

[assistant]
enabled = true
model = "phi4-mini"  # or "qwen3:4b"
window_size_seconds = 180  # 3-minute analysis windows
overlap_seconds = 30   # Overlap for context continuity

[ollama]
base_url = "http://localhost:11434"

[vault]
root = "~/Obsidian/Scribe"  # Vault folder path
```

### Plugin Settings

- **Server URL**: WebSocket endpoint (default: ws://localhost:8000)
- **Vault Folder**: Base folder for meeting notes (default: "Scribe/")
- **Model Selection**: Choose between available Ollama models

## Usage

1. **Start a meeting**
   - Open the Meeting Scribe plugin panel in Obsidian
   - Click "Start Recording"
   - Adjust speaker names by clicking on them in the transcript

2. **Watch analysis in real-time**
   - Rolling summary updates every ~3 minutes
   - Topics are automatically detected and organized
   - Action items are extracted and highlighted

3. **End the meeting**
   - Click "Stop Recording"
   - Plugin exports final transcript to markdown
   - Notes are saved to your vault
   - Use the skills system to customize future analysis

## Testing

```bash
cd server
pytest tests/
```

Key test files:
- `tests/test_skills.py` - Skills system functionality
- `tests/test_topic_detection.py` - Topic detection accuracy

## Development

### Contributing Skills

Add custom skills to `{vault}/Scribe/_assistant/skills/` as markdown files:

```markdown
---
type: skill
created: 2026-03-12
source: user
confidence: 0.8
---

# My Custom Skill

## When to use
[describe the context]

## Instructions
[behavior instructions for the assistant]
```

### Extending the Assistant

The assistant is built as a pipeline stage in `server/src/assistant.py`. Key extension points:

- **Models**: Add new models in `SkillsLoader`
- **Message types**: Extend `models.py` for new WebSocket messages
- **Analysis**: Enhance processing in `assistant.py`

## Known Limitations

- Context window limited by model size (mitigated by overlapping windows)
- Long sessions (4+ hours) benefit from frontier model (Claude API) for synthesis

## Troubleshooting

### Assistant not responding
- Check Ollama is running: `curl http://localhost:11434/api/tags`
- Verify model is installed: `ollama list`
- Check server logs for errors

### Vault notes not created
- Verify vault path in plugin settings
- Check plugin has write permissions to vault folder
- Review server logs for vault manager errors

### Speaker names resetting
- Names are local to current session only
- Use the vault to create persistent speaker profiles

## Roadmap

- [ ] Claude API escalation for complex synthesis
- [ ] Gitea/Wekan integration for task tracking
- [ ] Progressive idea refinement across sessions
- [ ] Embedding-based topic matching
- [ ] Multi-language support

## License

All rights reserved

## Support

- **Issues**: [GitHub Issues](https://github.com/WastelandWares/meeting-scribe/issues)
- **Design Docs**: See `docs/plans/` for architecture and sprint plans
