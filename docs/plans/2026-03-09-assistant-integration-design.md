# Meeting Scribe AI Assistant — Design Document

**Date**: 2026-03-09
**Author**: Elara (PM) + Thomas
**Status**: Approved — Sprint 1 in progress

## Overview

Integrate an AI assistant into the meeting-scribe pipeline that interprets live transcription, maintains meeting minutes, extracts action items, organizes notes by topic, and progressively refines ideas over time.

## Architecture

```
                    ┌─ Stream 1: immediate broadcast ─────> Plugin (live transcript)
audio -> STT ->  ──┤
                    └─ Stream 2: accumulator ─> Assistant ─> Plugin (minutes/topics/actions)
                         (overlapping 2-5 min batches)    |
                                                          v
                                                    Ollama API (local)
                                                          |
                                                    [escalation if needed]
                                                          v
                                                    Claude API (frontier)
```

### Key Decisions

1. **Assistant is a pipeline stage** in the Python server (`src/assistant.py`), not a sidecar
2. **Dual-stream processing**: real-time transcript (existing) + batched assistant analysis (new)
3. **Local model via Ollama**: Phi-4-mini (3.8B, 128K ctx) or Qwen3 4B (256K ctx) — benchmark both
4. **Frontier escalation**: Claude API for complex synthesis, batched for cost management
5. **Skills system**: Markdown files that teach the assistant, starts as blank slate ("new hire")

### Processing Cadence

- **Real-time (Stream 1)**: Every chunk → transcribe → broadcast (unchanged)
- **Assistant (Stream 2)**: Accumulate segments, process overlapping 2-5 min windows
- Overlap: 30-60s with previous window for context continuity

## Vault Folder Structure

```
{root}/                          # Configurable, e.g., "Scribe/"
├── meetings/                    # Daily minutes and session summaries
│   ├── 2026-03-09-minutes.md   # Appended per session, never duplicated
│   └── 2026-03-08-minutes.md
├── topics/                      # One note per topic, progressively refined
│   ├── voice-identification.md
│   ├── multi-device-capture.md
│   └── assistant-architecture.md
├── action-items.md              # Running tracker
└── _assistant/                  # Assistant's own workspace
    ├── context.md               # Accumulated context/memory
    └── skills/                  # Learnable behavioral instructions
        ├── summarization.md
        └── topic-detection.md
```

### Daily Minutes Logic

- File: `{root}/meetings/YYYY-MM-DD-minutes.md`
- If file exists for today → append `## Session N`
- If not → create with Session 1
- Never create duplicate daily files

## Model Strategy

### Hardware: M2 Max 32GB (unified memory)

| Model | Params | Ollama Size | Context | Best For |
|-------|--------|-------------|---------|----------|
| **Phi-4-mini** | 3.8B | 2.5GB | 128K | Reasoning, tool calling, structured output |
| **Qwen3 4B** | 4B | 2.5GB | 256K | Long sessions (4+ hrs), large context |
| **Granite 3.1 2B** | 2.5B | 1.6GB | 4K | Fastest, but limited context |
| **mxbai-embed-large** | 335M | 669MB | — | Embedding similarity for topic matching |

Total VRAM budget: ~4-5GB for assistant models, leaving headroom for Whisper + pyannote.

### Frontier Escalation (Claude API)

- End-of-session synthesis
- Cross-topic connection discovery
- Design doc / story generation
- Explicit user request
- Batched to manage cost

## New WebSocket Message Types

| Type | Direction | Payload |
|------|-----------|---------|
| `assistant_summary` | server→client | `{summary: string, session: number, timestamp: number}` |
| `assistant_action_items` | server→client | `{items: [{text, assignee?, source_segment_id}]}` |
| `assistant_topic_change` | server→client | `{topic_id, title, start_time, segments}` |
| `assistant_note_action` | server→client | `{action: create|update|link, path, content}` |

## Skills System

The assistant loads behavioral instructions from markdown files in `_assistant/skills/`.

### Skill File Format
```markdown
---
type: skill
created: 2026-03-09
source: manual | generated
confidence: 0.8
---
# Skill Name

## When to use
[context for when this skill applies]

## Instructions
[behavioral instructions for the assistant]
```

### Philosophy
- Start as blank slate — no pre-baked assumptions
- Build context from existing vault content
- Learn preferences from patterns and corrections
- Generate skill proposals after N sessions
- Human can edit/approve/reject skills

## Sprint Plan

### Sprint 1: Assistant Foundation (2 weeks, ending 2026-03-23)

| # | Story | Complexity | Dependency |
|---|-------|-----------|------------|
| 28 | Ollama model provisioning and health checks | small | none |
| 17 | Assistant service skeleton with Ollama integration | large | #28 |
| 27 | Dual-stream processing | medium | #17 |
| 18 | Rolling meeting summary | small | #17 |
| 19 | Action item extraction | small | #17 |

**Sprint 1 Goal**: Working server-side assistant that produces summaries and action items. No plugin UI yet — validate via raw WS messages.

### Sprint 2: Organization + Plugin UI

| # | Story | Complexity |
|---|-------|-----------|
| 24 | Plugin UI: assistant panel | medium |
| 20 | Topic segmentation | medium |
| 21 | Vault folder structure and note CRUD | medium |

### Sprint 3: Refinement + Learning

| # | Story | Complexity |
|---|-------|-----------|
| 22 | Progressive idea refinement | large |
| 23 | Skills system | medium |

### Sprint 4: Frontier + Integration

| # | Story | Complexity |
|---|-------|-----------|
| 25 | Frontier model escalation | medium |

## Open Questions

1. ~~Model selection~~ → Benchmark Phi-4-mini vs Qwen3 4B in Sprint 1
2. Topic matching: embeddings (mxbai-embed-large) vs LLM prompting vs hybrid?
3. Note CRUD: server writes files directly, or sends instructions to plugin?
4. How does the assistant handle very long sessions (4+ hours) with context limits?
