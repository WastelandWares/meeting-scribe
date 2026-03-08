import { ItemView, WorkspaceLeaf } from "obsidian";

export const VIEW_TYPE_TRANSCRIPT = "meeting-scribe-transcript";

interface Segment {
    id: string;
    speaker_id: string;
    speaker_name?: string;
    start: number;
    end: number;
    text: string;
}

type ConnectionStatus = "connected" | "disconnected" | "connecting";

export class TranscriptView extends ItemView {
    private segments: Segment[] = [];
    private connectionStatus: ConnectionStatus = "disconnected";
    private headerEl: HTMLElement;
    private segmentsEl: HTMLElement;
    private statusEl: HTMLElement;
    private speakerColorMap: Map<string, number> = new Map();
    private nextColorIndex = 0;

    /** Callback wired by the plugin to send WS control messages. */
    onControlAction: ((action: "start" | "pause" | "stop") => void) | null =
        null;

    /** Callback wired by the plugin to send speaker label changes. */
    onLabelSpeaker:
        | ((speakerId: string, name: string) => void)
        | null = null;

    constructor(leaf: WorkspaceLeaf) {
        super(leaf);
    }

    getViewType(): string {
        return VIEW_TYPE_TRANSCRIPT;
    }

    getDisplayText(): string {
        return "Meeting Scribe";
    }

    getIcon(): string {
        return "mic";
    }

    async onOpen(): Promise<void> {
        const container = this.contentEl;
        container.empty();
        container.addClass("meeting-scribe-view");

        // --- Header bar with controls ---
        this.headerEl = container.createDiv({ cls: "meeting-scribe-header" });

        this.statusEl = this.headerEl.createSpan({
            cls: "meeting-scribe-status",
            text: this.connectionStatus,
        });

        const controls = this.headerEl.createDiv({
            cls: "meeting-scribe-controls",
        });

        const startBtn = controls.createEl("button", { text: "Start" });
        startBtn.addEventListener("click", () =>
            this.onControlAction?.("start")
        );

        const pauseBtn = controls.createEl("button", { text: "Pause" });
        pauseBtn.addEventListener("click", () =>
            this.onControlAction?.("pause")
        );

        const stopBtn = controls.createEl("button", { text: "Stop" });
        stopBtn.addEventListener("click", () =>
            this.onControlAction?.("stop")
        );

        // --- Scrollable segments area ---
        this.segmentsEl = container.createDiv({
            cls: "meeting-scribe-segments",
        });

        this.renderSegments();
    }

    async onClose(): Promise<void> {
        this.contentEl.empty();
    }

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    /** Append or update segments (used on `segments` events). */
    updateSegments(incoming: Segment[]): void {
        for (const seg of incoming) {
            const idx = this.segments.findIndex((s) => s.id === seg.id);
            if (idx >= 0) {
                this.segments[idx] = seg;
            } else {
                this.segments.push(seg);
            }
        }
        this.renderSegments();
    }

    /** Replace all segments (used on `diarization_update` events). */
    replaceAllSegments(segments: Segment[]): void {
        this.segments = segments;
        this.renderSegments();
        // Brief flash to indicate a full re-render happened.
        this.segmentsEl.addClass("meeting-scribe-flash");
        setTimeout(() => {
            this.segmentsEl.removeClass("meeting-scribe-flash");
        }, 600);
    }

    /** Update the connection status indicator. */
    setConnectionStatus(status: ConnectionStatus): void {
        this.connectionStatus = status;
        if (this.statusEl) {
            this.statusEl.textContent = status;
            this.statusEl.className = `meeting-scribe-status status-${status}`;
        }
    }

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------

    private renderSegments(): void {
        if (!this.segmentsEl) return;
        this.segmentsEl.empty();

        for (const seg of this.segments) {
            const row = this.segmentsEl.createDiv({
                cls: "meeting-scribe-segment",
            });

            // Timestamp [MM:SS]
            const ts = this.formatTimestamp(seg.start);
            row.createSpan({
                cls: "meeting-scribe-timestamp",
                text: `[${ts}] `,
            });

            // Speaker name (clickable for inline rename)
            const speakerEl = row.createSpan({
                cls: `meeting-scribe-speaker ${this.speakerClass(seg.speaker_id)}`,
                text: seg.speaker_name ?? seg.speaker_id,
            });

            speakerEl.addEventListener("click", () => {
                this.showSpeakerRenameInput(speakerEl, seg.speaker_id);
            });

            row.createSpan({ text: ": " });

            // Segment text
            row.createSpan({
                cls: "meeting-scribe-text",
                text: seg.text,
            });
        }

        // Auto-scroll to bottom
        this.segmentsEl.scrollTop = this.segmentsEl.scrollHeight;
    }

    private showSpeakerRenameInput(
        speakerEl: HTMLSpanElement,
        speakerId: string
    ): void {
        const currentName = speakerEl.textContent ?? speakerId;
        const input = document.createElement("input");
        input.type = "text";
        input.value = currentName;
        input.className = "meeting-scribe-rename-input";

        const commit = () => {
            const newName = input.value.trim();
            if (newName && newName !== currentName) {
                // Update all segments with this speaker id
                for (const seg of this.segments) {
                    if (seg.speaker_id === speakerId) {
                        seg.speaker_name = newName;
                    }
                }
                this.onLabelSpeaker?.(speakerId, newName);
            }
            this.renderSegments();
        };

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                commit();
            } else if (e.key === "Escape") {
                this.renderSegments();
            }
        });

        input.addEventListener("blur", commit);

        speakerEl.textContent = "";
        speakerEl.appendChild(input);
        input.focus();
        input.select();
    }

    private formatTimestamp(seconds: number): string {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }

    private speakerClass(speakerId: string): string {
        if (!this.speakerColorMap.has(speakerId)) {
            this.speakerColorMap.set(speakerId, this.nextColorIndex++);
        }
        return `speaker-${this.speakerColorMap.get(speakerId)!}`;
    }
}
