/** A single transcript segment from the server. */
export interface Segment {
    id: string;
    speaker_id: string;
    speaker_name?: string;
    start: number;
    end: number;
    text: string;
}

/** Payload for a `diarization_update` message. */
export interface DiarizationUpdate {
    revision: number;
    segments: Segment[];
}

/** Payload for a `status` message. */
export interface StatusData {
    state: 'recording' | 'paused' | 'stopped' | 'processing';
}

// ── Assistant message types (Stream 2) ──────────────────────

/** A single action item extracted by the assistant. */
export interface ActionItem {
    text: string;
    assignee: string | null;
    priority: 'high' | 'medium' | 'low';
}

/** Payload for an `assistant_summary` message. */
export interface AssistantSummary {
    summary: string;
    topics: string[];
    analysis_number: number;
    window_start: number;
    window_end: number;
}

/** Payload for an `assistant_action_items` message. */
export interface AssistantActionItems {
    items: ActionItem[];
    analysis_number: number;
}

/** Payload for an `assistant_status` message. */
export interface AssistantStatus {
    status: 'initializing' | 'analyzing' | 'ready' | 'error' | 'unavailable' | 'waiting';
    message?: string;
    model?: string;
    countdown_seconds?: number;
    segments_accumulated?: number;
    window_seconds?: number;
}

/** Payload for an `assistant_topic_change` message. */
export interface TopicChange {
    new_topic: string;
    previous_topic: string | null;
    timestamp: number;
    confidence: number;
}

export interface AssistantTopicChange {
    topic: TopicChange;
    all_topics: TopicChange[];
}

// ── Server info (sent on connect) ───────────────────────────

/** A warning/info banner from the server. */
export interface ServerWarning {
    id: string;
    level: 'warning' | 'info' | 'error';
    title: string;
    message: string;
}

/** Payload for a `server_info` message (sent on connect). */
export interface ServerInfo {
    diarization: boolean;
    assistant: boolean;
    assistant_window: number;
    assistant_model?: string;
    warnings: ServerWarning[];
}
