# Changelog

All notable changes to Meeting Scribe will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-03-12

### Added
- **Vault structure and organization** (Issue #20):
  - VaultManager for automated note creation and updates
  - Obsidian-native folder structure: meetings, topics, action-items, _assistant
  - Daily minutes files (never duplicated) with per-session sections
  - Topic notes with progressive refinement
  - Automatic action item tracker
- **Skills system** (Issue #23):
  - Markdown-based behavioral instructions for assistant learning
  - Built-in skills: action-tracker, summarizer
  - User skills support for customization
  - Skills loader with metadata (source, created date, confidence)
- **Enhanced topic detection** (Issue #21):
  - Comprehensive test coverage for topic detection
  - Integration with vault structure for topic organization
- **Type system expansion**: Assistant message types for topic changes and note actions
- **Tests**: Full test suite for topic detection and skills system

### Changed
- Plugin transcript view now integrates with vault topic organization
- Assistant workflow now includes vault note creation and updates
- Skills system enables progressive assistant learning from vault content

## [0.2.0] - 2026-03-09

### Added
- **AI Assistant (Stream 2)**: Real-time meeting analysis via local Ollama models
  - Rolling summary updated every ~3 minutes
  - Automatic action item extraction from conversation
  - Topic detection and tagging
  - Configurable analysis window and model selection
- **Ollama client**: Async client with health checks, model auto-detection, chat completions
  - Preferred models: phi4-mini, qwen3:4b (auto-selects best available)
- **Plugin UI overhaul**:
  - Status indicator with colored dot + label (fixes truncated text)
  - Color-coded Start/Pause/Stop buttons with icons
  - Recording indicator bar with pulsing red dot
  - Live elapsed-time timer
  - Empty state with instructions
  - Assistant panel showing summary, topics, and action items
  - Proper flexbox layout with scrollable transcript area
  - Obsidian theme variable support for dark/light mode compatibility
- **Assistant message types**: `assistant_summary`, `assistant_action_items`, `assistant_status`
- **Server configuration**: `config.example.toml` for deployment reference
- **CLI flags**: `--no-assistant`, `--assistant-model`, `--ollama-url`, `--assistant-window`
- **Test plan**: Step-by-step guide for live testing with two speakers

### Fixed
- Build backend changed from invalid `setuptools.backends._legacy:_Backend` to `setuptools.build_meta`
- Plugin no longer silently drops unknown WebSocket message types

## [0.1.0] - 2026-03-08

### Added
- Real-time audio capture and transcription via faster-whisper
- WebSocket server for streaming segments to clients
- Speaker diarization with pyannote.audio
- Obsidian plugin with live transcript view
- Inline speaker renaming (click to edit)
- Diarization flash animation on re-render
- Periodic interim writes for crash recovery
- Final transcript export to markdown
- Speaker color palette (6-color rotation)
- Auto-reconnect with exponential backoff
- Settings tab for server URL, model, output folder
