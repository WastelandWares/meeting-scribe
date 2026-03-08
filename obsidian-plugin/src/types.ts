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
