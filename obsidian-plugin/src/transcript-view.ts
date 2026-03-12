import { ItemView, WorkspaceLeaf } from "obsidian";
import type {
    AssistantSummary,
    AssistantActionItems,
    AssistantStatus,
    AssistantTopicChange,
    ActionItem,
    ServerInfo,
    ServerWarning,
} from "./types";

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
    private isRecording = false;

    // DOM refs
    private headerEl: HTMLElement;
    private statusDotEl: HTMLElement;
    private statusTextEl: HTMLElement;
    private timerEl: HTMLElement;
    private controlsEl: HTMLElement;
    private recordingBarEl: HTMLElement;
    private bannersEl: HTMLElement;
    private segmentsEl: HTMLElement;
    private emptyStateEl: HTMLElement;

    // Assistant DOM refs
    private assistantEl: HTMLElement;
    private assistantStatusEl: HTMLElement;
    private assistantCountdownEl: HTMLElement;
    private summaryEl: HTMLElement;
    private actionItemsEl: HTMLElement;
    private topicsEl: HTMLElement;

    // State
    private speakerColorMap: Map<string, number> = new Map();
    private nextColorIndex = 0;
    private latestSummary: AssistantSummary | null = null;
    private latestActionItems: ActionItem[] = [];
    private recordingStartMs = 0;
    private timerInterval: ReturnType<typeof setInterval> | null = null;
    private dismissedBanners: Set<string> = new Set();
    private assistantWindowSeconds = 180;

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

        // ── Header bar ───────────────────────────────────────
        this.headerEl = container.createDiv({ cls: "meeting-scribe-header" });

        const statusArea = this.headerEl.createDiv({
            cls: "meeting-scribe-status-area",
        });

        this.statusDotEl = statusArea.createSpan({
            cls: `meeting-scribe-status-dot status-${this.connectionStatus}`,
        });
        this.statusTextEl = statusArea.createSpan({
            cls: "meeting-scribe-status-text",
            text: this.connectionStatus,
        });

        this.timerEl = this.headerEl.createSpan({
            cls: "meeting-scribe-timer",
            text: "",
        });

        this.controlsEl = this.headerEl.createDiv({
            cls: "meeting-scribe-controls",
        });

        this.createControlButtons();

        // ── Recording indicator bar ──────────────────────────
        this.recordingBarEl = container.createDiv({
            cls: "meeting-scribe-recording-bar",
        });
        this.recordingBarEl.createSpan({ cls: "meeting-scribe-rec-dot" });
        this.recordingBarEl.createSpan({ text: "Recording" });

        // ── Banners container ─────────────────────────────────
        this.bannersEl = container.createDiv({
            cls: "meeting-scribe-banners",
        });

        // ── Assistant panel ──────────────────────────────────
        this.assistantEl = container.createDiv({
            cls: "meeting-scribe-assistant",
        });

        const assistantHeader = this.assistantEl.createDiv({
            cls: "meeting-scribe-assistant-header",
        });
        assistantHeader.createSpan({ text: "Assistant" });
        this.assistantStatusEl = assistantHeader.createSpan({
            cls: "meeting-scribe-assistant-status",
            text: "",
        });

        this.assistantCountdownEl = this.assistantEl.createDiv({
            cls: "meeting-scribe-countdown",
        });
        this.assistantCountdownEl.style.display = "none";

        this.summaryEl = this.assistantEl.createDiv({
            cls: "meeting-scribe-summary",
        });

        this.actionItemsEl = this.assistantEl.createDiv({
            cls: "meeting-scribe-action-items",
        });

        this.topicsEl = this.assistantEl.createDiv({
            cls: "meeting-scribe-topics-section",
        });

        // Hidden until assistant sends first update or server_info arrives
        this.assistantEl.style.display = "none";

        // ── Empty state ──────────────────────────────────────
        this.emptyStateEl = container.createDiv({
            cls: "meeting-scribe-empty",
        });
        this.emptyStateEl.createDiv({
            cls: "meeting-scribe-empty-icon",
            text: "\uD83C\uDFA4",
        });
        this.emptyStateEl.createDiv({
            cls: "meeting-scribe-empty-title",
            text: "No transcript yet",
        });
        this.emptyStateEl.createDiv({
            cls: "meeting-scribe-empty-hint",
            text: "Click Start to begin recording, or use the command palette: Meeting Scribe: Start Meeting",
        });

        // ── Scrollable segments area ─────────────────────────
        this.segmentsEl = container.createDiv({
            cls: "meeting-scribe-segments",
        });

        this.renderSegments();
    }

    async onClose(): Promise<void> {
        this.stopTimer();
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
        this.segmentsEl.addClass("meeting-scribe-flash");
        setTimeout(() => {
            this.segmentsEl.removeClass("meeting-scribe-flash");
        }, 600);
    }

    /** Update the connection status indicator. */
    setConnectionStatus(status: ConnectionStatus): void {
        this.connectionStatus = status;
        if (this.statusDotEl) {
            this.statusDotEl.className = `meeting-scribe-status-dot status-${status}`;
        }
        if (this.statusTextEl) {
            this.statusTextEl.textContent = status;
        }
    }

    /** Show the latest assistant summary. */
    updateAssistantSummary(data: AssistantSummary): void {
        this.latestSummary = data;
        this.assistantEl.style.display = "";
        this.renderSummary();
    }

    /** Show the latest assistant action items. */
    updateAssistantActionItems(data: AssistantActionItems): void {
        this.latestActionItems = data.items;
        this.assistantEl.style.display = "";
        this.renderActionItems();
    }

    /** Show a topic change notification. */
    updateTopicChange(data: AssistantTopicChange): void {
        this.assistantEl.style.display = "";
        this.renderTopics(data);
    }

    /** Update the assistant status indicator. */
    updateAssistantStatus(data: AssistantStatus): void {
        this.assistantEl.style.display = "";

        if (this.assistantStatusEl) {
            if (data.status === "waiting" && data.countdown_seconds !== undefined) {
                // Show countdown
                const mins = Math.floor(data.countdown_seconds / 60);
                const secs = Math.floor(data.countdown_seconds % 60);
                const timeStr = mins > 0
                    ? `${mins}m ${String(secs).padStart(2, "0")}s`
                    : `${secs}s`;
                this.assistantStatusEl.textContent = ` (next analysis in ${timeStr})`;
                this.assistantStatusEl.className = "meeting-scribe-assistant-status assistant-waiting";

                // Update countdown bar
                if (this.assistantCountdownEl) {
                    this.assistantCountdownEl.style.display = "";
                    const pct = Math.max(0, Math.min(100,
                        100 * (1 - data.countdown_seconds / this.assistantWindowSeconds)));
                    this.renderCountdown(pct, data.segments_accumulated ?? 0, data.countdown_seconds);
                }
            } else {
                const icon =
                    data.status === "analyzing"
                        ? " ..."
                        : data.status === "error"
                            ? " !"
                            : "";
                this.assistantStatusEl.textContent = ` (${data.status}${icon})`;
                this.assistantStatusEl.className = `meeting-scribe-assistant-status assistant-${data.status}`;

                // Hide countdown when analyzing or showing results
                if (this.assistantCountdownEl && data.status !== "waiting") {
                    this.assistantCountdownEl.style.display = "none";
                }
            }
        }
    }

    /** Handle server_info message — show banners for missing capabilities. */
    showServerInfo(info: ServerInfo): void {
        this.assistantWindowSeconds = info.assistant_window || 180;

        // Show assistant panel header if assistant is enabled (even if waiting)
        if (info.assistant) {
            this.assistantEl.style.display = "";
            if (info.assistant_model) {
                this.assistantStatusEl.textContent = ` (${info.assistant_model})`;
                this.assistantStatusEl.className = "meeting-scribe-assistant-status assistant-ready";
            }
        }

        // Render warning/info banners
        for (const warning of info.warnings) {
            if (!this.dismissedBanners.has(warning.id)) {
                this.addBanner(warning);
            }
        }
    }

    /** Add a banner notification. */
    private addBanner(warning: ServerWarning): void {
        if (!this.bannersEl) return;

        // Don't duplicate
        const existing = this.bannersEl.querySelector(`[data-banner-id="${warning.id}"]`);
        if (existing) return;

        const banner = this.bannersEl.createDiv({
            cls: `meeting-scribe-banner banner-${warning.level}`,
        });
        banner.setAttribute("data-banner-id", warning.id);

        const iconMap: Record<string, string> = {
            warning: "\u26A0",
            info: "\u2139",
            error: "\u2716",
        };

        const content = banner.createDiv({ cls: "meeting-scribe-banner-content" });
        content.createSpan({
            cls: "meeting-scribe-banner-icon",
            text: iconMap[warning.level] || "\u2139",
        });
        const textArea = content.createDiv({ cls: "meeting-scribe-banner-text" });
        textArea.createDiv({
            cls: "meeting-scribe-banner-title",
            text: warning.title,
        });
        textArea.createDiv({
            cls: "meeting-scribe-banner-message",
            text: warning.message,
        });

        const dismissBtn = banner.createEl("button", {
            cls: "meeting-scribe-banner-dismiss",
            text: "\u2715",
        });
        dismissBtn.addEventListener("click", () => {
            this.dismissedBanners.add(warning.id);
            banner.remove();
        });
    }

    /** Notify the view that recording has started. */
    setRecording(recording: boolean): void {
        this.isRecording = recording;
        if (this.recordingBarEl) {
            if (recording) {
                this.recordingBarEl.addClass("is-recording");
                this.startTimer();
            } else {
                this.recordingBarEl.removeClass("is-recording");
                this.stopTimer();
            }
        }
    }

    // ------------------------------------------------------------------
    // Control buttons
    // ------------------------------------------------------------------

    private createControlButtons(): void {
        const startBtn = this.controlsEl.createEl("button", {
            cls: "meeting-scribe-btn btn-start",
        });
        startBtn.createSpan({ cls: "meeting-scribe-btn-icon", text: "\u25B6" });
        startBtn.createSpan({ text: "Start" });
        startBtn.addEventListener("click", () => {
            this.onControlAction?.("start");
            this.setRecording(true);
        });

        const pauseBtn = this.controlsEl.createEl("button", {
            cls: "meeting-scribe-btn btn-pause",
        });
        pauseBtn.createSpan({ cls: "meeting-scribe-btn-icon", text: "\u23F8" });
        pauseBtn.createSpan({ text: "Pause" });
        pauseBtn.addEventListener("click", () =>
            this.onControlAction?.("pause")
        );

        const stopBtn = this.controlsEl.createEl("button", {
            cls: "meeting-scribe-btn btn-stop",
        });
        stopBtn.createSpan({ cls: "meeting-scribe-btn-icon", text: "\u25A0" });
        stopBtn.createSpan({ text: "Stop" });
        stopBtn.addEventListener("click", () => {
            this.onControlAction?.("stop");
            this.setRecording(false);
        });
    }

    // ------------------------------------------------------------------
    // Timer
    // ------------------------------------------------------------------

    private startTimer(): void {
        this.stopTimer();
        this.recordingStartMs = Date.now();
        this.timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - this.recordingStartMs) / 1000);
            const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
            const ss = String(elapsed % 60).padStart(2, "0");
            if (this.timerEl) {
                this.timerEl.textContent = `${mm}:${ss}`;
            }
        }, 1000);
    }

    private stopTimer(): void {
        if (this.timerInterval !== null) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    // ------------------------------------------------------------------
    // Segment rendering
    // ------------------------------------------------------------------

    private isRendering = false;

    private renderSegments(): void {
        if (!this.segmentsEl || this.isRendering) return;
        this.isRendering = true;

        // Toggle empty state vs segments
        if (this.emptyStateEl) {
            this.emptyStateEl.style.display =
                this.segments.length === 0 ? "" : "none";
        }
        this.segmentsEl.style.display =
            this.segments.length === 0 ? "none" : "";

        // Clear and re-render
        while (this.segmentsEl.firstChild) {
            this.segmentsEl.removeChild(this.segmentsEl.firstChild);
        }

        for (const seg of this.segments) {
            const row = this.segmentsEl.createDiv({
                cls: "meeting-scribe-segment",
            });

            // Timestamp [MM:SS]
            const ts = this.formatTimestamp(seg.start);
            row.createSpan({
                cls: "meeting-scribe-timestamp",
                text: `${ts}`,
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
        this.isRendering = false;
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

        let committed = false;
        const commit = () => {
            if (committed) return;
            committed = true;
            const newName = input.value.trim();
            if (newName && newName !== currentName) {
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
                committed = true;
                this.renderSegments();
            }
        });

        input.addEventListener("blur", () => commit());

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

    // ------------------------------------------------------------------
    // Assistant rendering
    // ------------------------------------------------------------------

    private renderSummary(): void {
        if (!this.summaryEl || !this.latestSummary) return;

        while (this.summaryEl.firstChild) {
            this.summaryEl.removeChild(this.summaryEl.firstChild);
        }

        this.summaryEl.createEl("h4", { text: "Summary" });
        this.summaryEl.createEl("p", {
            cls: "meeting-scribe-summary-text",
            text: this.latestSummary.summary,
        });

        if (this.latestSummary.topics.length > 0) {
            const topicsEl = this.summaryEl.createDiv({
                cls: "meeting-scribe-topics",
            });
            topicsEl.createSpan({
                cls: "meeting-scribe-topics-label",
                text: "Topics: ",
            });
            for (const topic of this.latestSummary.topics) {
                topicsEl.createSpan({
                    cls: "meeting-scribe-topic-tag",
                    text: topic,
                });
            }
        }
    }

    private renderActionItems(): void {
        if (!this.actionItemsEl) return;

        while (this.actionItemsEl.firstChild) {
            this.actionItemsEl.removeChild(this.actionItemsEl.firstChild);
        }

        if (this.latestActionItems.length === 0) return;

        this.actionItemsEl.createEl("h4", { text: "Action Items" });
        const list = this.actionItemsEl.createEl("ul", {
            cls: "meeting-scribe-action-list",
        });

        for (const item of this.latestActionItems) {
            const li = list.createEl("li", {
                cls: `meeting-scribe-action-item priority-${item.priority}`,
            });
            li.createSpan({
                cls: "meeting-scribe-action-text",
                text: item.text,
            });
            if (item.assignee) {
                li.createSpan({
                    cls: "meeting-scribe-action-assignee",
                    text: ` @${item.assignee}`,
                });
            }
        }
    }

    private renderTopics(data: AssistantTopicChange): void {
        if (!this.topicsEl) return;

        while (this.topicsEl.firstChild) {
            this.topicsEl.removeChild(this.topicsEl.firstChild);
        }

        this.topicsEl.createEl("h4", { text: "Topics" });

        const currentEl = this.topicsEl.createDiv({
            cls: "meeting-scribe-current-topic",
        });
        currentEl.createSpan({
            cls: "meeting-scribe-topic-label",
            text: "Current: ",
        });
        currentEl.createSpan({
            cls: "meeting-scribe-topic-tag",
            text: data.topic.new_topic,
        });

        if (data.all_topics.length > 1) {
            const historyEl = this.topicsEl.createDiv({
                cls: "meeting-scribe-topic-history",
            });
            historyEl.createSpan({
                cls: "meeting-scribe-topic-label",
                text: "Previous: ",
            });
            // Show last 5 topics in reverse
            const recent = data.all_topics.slice(-6, -1).reverse();
            for (const t of recent) {
                historyEl.createSpan({
                    cls: "meeting-scribe-topic-tag topic-past",
                    text: t.new_topic,
                });
            }
        }
    }

    // ------------------------------------------------------------------
    // Countdown progress bar
    // ------------------------------------------------------------------

    private renderCountdown(pct: number, segCount: number, remaining: number): void {
        if (!this.assistantCountdownEl) return;

        while (this.assistantCountdownEl.firstChild) {
            this.assistantCountdownEl.removeChild(this.assistantCountdownEl.firstChild);
        }

        const barContainer = this.assistantCountdownEl.createDiv({
            cls: "meeting-scribe-countdown-bar",
        });

        const fill = barContainer.createDiv({
            cls: "meeting-scribe-countdown-fill",
        });
        fill.style.width = `${pct}%`;

        const label = this.assistantCountdownEl.createDiv({
            cls: "meeting-scribe-countdown-label",
        });

        const mins = Math.floor(remaining / 60);
        const secs = Math.floor(remaining % 60);
        const timeStr = mins > 0
            ? `${mins}m ${String(secs).padStart(2, "0")}s`
            : `${secs}s`;
        label.textContent = `${segCount} segments collected \u2022 analysis in ${timeStr}`;
    }
}
