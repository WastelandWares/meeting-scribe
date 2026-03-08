import { Plugin, WorkspaceLeaf } from "obsidian";
import { WSClient } from "./ws-client";
import { SpeakerStore } from "./speaker-store";
import { MarkdownWriter } from "./markdown-writer";
import {
    MeetingScribeSettingTab,
    DEFAULT_SETTINGS,
} from "./settings";
import type { MeetingScribeSettings } from "./settings";
import type { Segment, DiarizationUpdate, StatusData } from "./types";
import { TranscriptView, VIEW_TYPE_TRANSCRIPT } from "./transcript-view";

const INTERIM_WRITE_INTERVAL_MS = 60_000;

export default class MeetingScribePlugin extends Plugin {
    settings: MeetingScribeSettings = DEFAULT_SETTINGS;

    private wsClient: WSClient;
    private speakerStore: SpeakerStore;
    private markdownWriter: MarkdownWriter;
    private interimTimer: ReturnType<typeof setInterval> | null = null;
    private allSegments: Segment[] = [];
    private recordingStartTime = 0;

    async onload(): Promise<void> {
        console.log("[meeting-scribe] Loading plugin...");
        await this.loadSettings();

        this.wsClient = new WSClient(this.settings.serverUrl);
        this.speakerStore = new SpeakerStore();
        try {
            await this.speakerStore.loadFromVault(this.app.vault);
        } catch (e) {
            console.error("[meeting-scribe] Failed to load speaker store:", e);
        }
        this.markdownWriter = new MarkdownWriter(
            this.app.vault,
            this.settings.outputFolder,
        );

        // Register the transcript view type
        this.registerView(VIEW_TYPE_TRANSCRIPT, (leaf: WorkspaceLeaf) => {
            const view = new TranscriptView(leaf);
            this.wireViewCallbacks(view);
            return view;
        });

        // Ribbon icon to open/reveal the transcript view
        this.addRibbonIcon("mic", "Meeting Scribe", () => {
            this.activateTranscriptView();
        });

        // Command palette commands
        this.addCommand({
            id: "start-meeting",
            name: "Start Meeting",
            callback: () => {
                this.wsClient.connect();
                this.wsClient.send({ type: "start", model: this.settings.whisperModel });
                this.recordingStartTime = Date.now();
                this.startInterimWrites();
            },
        });

        this.addCommand({
            id: "stop-meeting",
            name: "Stop Meeting",
            callback: async () => {
                this.wsClient.send({ type: "stop" });
                this.stopInterimWrites();
                await this.finalizeMeeting();
            },
        });

        // Settings tab
        this.addSettingTab(new MeetingScribeSettingTab(this.app, this));

        // Wire WSClient callbacks
        this.wsClient.onSegments = (segments: Segment[]) => {
            console.log("[meeting-scribe] Received segments:", segments.length);
            this.mergeSegments(segments);
            const view = this.getTranscriptView();
            view?.updateSegments(segments);
        };

        this.wsClient.onDiarizationUpdate = (update: DiarizationUpdate) => {
            this.allSegments = update.segments;
            const view = this.getTranscriptView();
            view?.replaceAllSegments(update.segments);
        };

        this.wsClient.onStatus = (status: StatusData) => {
            // Status updates are informational; the view can use connection state
            // to reflect recording state. Log for debugging.
            console.log("[meeting-scribe] Server status:", status.state);
        };

        this.wsClient.onConnectionChange = (state) => {
            console.log("[meeting-scribe] Connection state:", state);
            const view = this.getTranscriptView();
            view?.setConnectionStatus(state);
        };

        // Auto-start if configured
        if (this.settings.autoStart) {
            this.wsClient.connect();
        }
    }

    onunload(): void {
        this.wsClient.disconnect();
        this.stopInterimWrites();
    }

    async loadSettings(): Promise<void> {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings(): Promise<void> {
        await this.saveData(this.settings);
        // Propagate URL changes to the client
        this.wsClient?.setUrl(this.settings.serverUrl);
    }

    // ------------------------------------------------------------------
    // Private helpers
    // ------------------------------------------------------------------

    /** Find the active TranscriptView, if one exists. */
    private getTranscriptView(): TranscriptView | null {
        const leaves = this.app.workspace.getLeavesOfType(VIEW_TYPE_TRANSCRIPT);
        if (leaves.length > 0) {
            return leaves[0].view as TranscriptView;
        }
        return null;
    }

    /** Open or reveal the transcript view in the right sidebar. */
    private async activateTranscriptView(): Promise<void> {
        const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE_TRANSCRIPT);
        if (existing.length > 0) {
            this.app.workspace.revealLeaf(existing[0]);
            return;
        }

        const leaf = this.app.workspace.getRightLeaf(false);
        if (leaf) {
            await leaf.setViewState({
                type: VIEW_TYPE_TRANSCRIPT,
                active: true,
            });
            this.app.workspace.revealLeaf(leaf);
        }
    }

    /** Wire control/label callbacks on a transcript view instance. */
    private wireViewCallbacks(view: TranscriptView): void {
        view.onControlAction = (action: "start" | "pause" | "stop") => {
            if (action === "start") {
                this.wsClient.connect();
                this.wsClient.send({ type: "start", model: this.settings.whisperModel });
                this.recordingStartTime = Date.now();
                this.startInterimWrites();
            } else if (action === "stop") {
                this.wsClient.send({ type: "stop" });
                this.stopInterimWrites();
                this.finalizeMeeting();
            } else {
                this.wsClient.send({ type: action });
            }
        };

        view.onLabelSpeaker = (speakerId: string, name: string) => {
            this.wsClient.send({
                type: "label_speaker",
                speaker_id: speakerId,
                name,
            });
            this.speakerStore.setLabel(speakerId, name);
            this.speakerStore.saveToVault(this.app.vault);
        };
    }

    /** Merge incoming segments into the master list. */
    private mergeSegments(incoming: Segment[]): void {
        for (const seg of incoming) {
            const idx = this.allSegments.findIndex((s) => s.id === seg.id);
            if (idx >= 0) {
                this.allSegments[idx] = seg;
            } else {
                this.allSegments.push(seg);
            }
        }
    }

    /** Start periodic interim writes (crash recovery). */
    private startInterimWrites(): void {
        this.stopInterimWrites();
        this.interimTimer = setInterval(() => {
            if (this.allSegments.length > 0) {
                const duration = (Date.now() - this.recordingStartTime) / 1000;
                this.markdownWriter.writeInterim(
                    this.allSegments,
                    duration,
                    this.speakerStore.getAllLabels(),
                );
            }
        }, INTERIM_WRITE_INTERVAL_MS);
    }

    /** Stop interim write interval. */
    private stopInterimWrites(): void {
        if (this.interimTimer !== null) {
            clearInterval(this.interimTimer);
            this.interimTimer = null;
        }
    }

    /** Finalize the transcript to a permanent markdown file. */
    private async finalizeMeeting(): Promise<void> {
        if (this.allSegments.length === 0) return;
        const duration = (Date.now() - this.recordingStartTime) / 1000;
        const file = await this.markdownWriter.finalize(
            this.allSegments,
            duration,
            this.speakerStore.getAllLabels(),
        );
        console.log("[meeting-scribe] Transcript saved:", file.path);
        this.allSegments = [];
    }
}
