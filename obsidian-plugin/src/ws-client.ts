import type { Segment, DiarizationUpdate, StatusData } from './types';

export type ConnectionState = 'connected' | 'connecting' | 'disconnected';

/**
 * WebSocket client for the meeting-scribe transcription server.
 *
 * Handles connection lifecycle, auto-reconnect with exponential backoff,
 * and dispatching incoming messages to typed callbacks.
 */
export class WSClient {
    private ws: WebSocket | null = null;
    private url: string;
    private shouldReconnect = false;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private backoffMs = 1000;

    private static readonly MIN_BACKOFF = 1000;
    private static readonly MAX_BACKOFF = 30000;
    private pendingMessages: object[] = [];

    state: ConnectionState = 'disconnected';

    // Callbacks — consumers assign these directly
    onSegments: ((segments: Segment[]) => void) | null = null;
    onDiarizationUpdate: ((update: DiarizationUpdate) => void) | null = null;
    onStatus: ((status: StatusData) => void) | null = null;
    onConnectionChange: ((state: ConnectionState) => void) | null = null;

    constructor(url: string) {
        this.url = url;
    }

    /** Open a WebSocket connection to the server. */
    connect(): void {
        if (this.ws) {
            this.disconnect();
        }

        this.shouldReconnect = true;
        this.backoffMs = WSClient.MIN_BACKOFF;
        this.setState('connecting');

        this.createSocket();
    }

    /** Tear down the connection and stop reconnecting. */
    disconnect(): void {
        this.shouldReconnect = false;

        if (this.reconnectTimer !== null) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.ws) {
            this.ws.onopen = null;
            this.ws.onclose = null;
            this.ws.onmessage = null;
            this.ws.onerror = null;
            this.ws.close();
            this.ws = null;
        }

        this.setState('disconnected');
    }

    /** Send a JSON message to the server. Queues if connecting. */
    send(msg: object): void {
        if (this.ws && this.state === 'connected') {
            this.ws.send(JSON.stringify(msg));
        } else {
            this.pendingMessages.push(msg);
        }
    }

    /** Update the server URL (takes effect on next connect). */
    setUrl(url: string): void {
        this.url = url;
    }

    // ── Private ───────────────────────────────────────────────

    private createSocket(): void {
        const ws = new WebSocket(this.url);

        ws.onopen = () => {
            this.backoffMs = WSClient.MIN_BACKOFF;
            this.setState('connected');
            // Flush any messages queued while connecting
            for (const msg of this.pendingMessages) {
                ws.send(JSON.stringify(msg));
            }
            this.pendingMessages = [];
        };

        ws.onclose = () => {
            this.ws = null;
            this.setState('disconnected');
            this.scheduleReconnect();
        };

        ws.onerror = () => {
            // onclose fires after onerror, so reconnect is handled there.
        };

        ws.onmessage = (event: MessageEvent) => {
            this.handleMessage(event);
        };

        this.ws = ws;
    }

    private handleMessage(event: MessageEvent): void {
        let msg: { type: string; data: unknown };
        try {
            msg = JSON.parse(event.data as string);
        } catch {
            console.error('[meeting-scribe] Failed to parse WS message:', event.data);
            return;
        }

        const data = msg.data as Record<string, unknown>;
        switch (msg.type) {
            case 'segments':
                this.onSegments?.((data.segments ?? data) as Segment[]);
                break;
            case 'diarization_update':
                this.onDiarizationUpdate?.(data as unknown as DiarizationUpdate);
                break;
            case 'status':
                this.onStatus?.(data as unknown as StatusData);
                break;
            default:
                console.warn('[meeting-scribe] Unknown WS message type:', msg.type);
        }
    }

    private scheduleReconnect(): void {
        if (!this.shouldReconnect) return;

        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.setState('connecting');
            this.createSocket();
        }, this.backoffMs);

        // Exponential backoff: 1s → 2s → 4s → … → 30s
        this.backoffMs = Math.min(this.backoffMs * 2, WSClient.MAX_BACKOFF);
    }

    private setState(newState: ConnectionState): void {
        if (this.state !== newState) {
            this.state = newState;
            this.onConnectionChange?.(newState);
        }
    }
}
