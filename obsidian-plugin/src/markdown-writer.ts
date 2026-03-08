import { Vault, TFile } from 'obsidian';
import type { Segment } from './types';

const INTERIM_FILENAME = '.meeting-scribe-interim.md';

/**
 * Builds and writes meeting transcript markdown files into the vault.
 *
 * Output format matches the post-hoc `transcribe.py` CLI: YAML frontmatter,
 * speaker legend, and blockquote transcript grouped by consecutive speaker turns.
 */
export class MarkdownWriter {
    private vault: Vault;
    private outputFolder: string;

    constructor(vault: Vault, outputFolder: string) {
        this.vault = vault;
        // Normalise: strip trailing slash
        this.outputFolder = outputFolder.replace(/\/+$/, '');
    }

    // ── Public API ────────────────────────────────────────────

    /**
     * Build the full markdown string for a transcript.
     *
     * @param segments  Ordered transcript segments
     * @param duration  Total recording duration in seconds
     * @param speakers  Map of speaker_id → display name
     */
    buildMarkdown(
        segments: Segment[],
        duration: number,
        speakers: Record<string, string>,
    ): string {
        const date = this.todayISO();
        const speakerList = Object.values(speakers).length > 0
            ? Object.values(speakers)
            : this.uniqueSpeakers(segments).map(id => speakers[id] ?? id);

        const lines: string[] = [];

        // --- YAML frontmatter ---
        lines.push('---');
        lines.push(`date: ${date}`);
        lines.push(`duration: ${fmtTimestamp(duration)}`);
        lines.push('speakers:');
        for (const name of this.orderedSpeakerNames(segments, speakers)) {
            lines.push(`  - ${name}`);
        }
        lines.push('---');
        lines.push('');

        // --- Speaker legend ---
        lines.push('## Speakers');
        lines.push('');
        for (const name of this.orderedSpeakerNames(segments, speakers)) {
            lines.push(`- **${name}**`);
        }
        lines.push('');

        // --- Transcript ---
        lines.push('## Transcript');
        lines.push('');
        this.appendTranscript(lines, segments, speakers);

        return lines.join('\n') + '\n';
    }

    /**
     * Write a crash-recovery interim file. Called periodically during recording.
     */
    async writeInterim(
        segments: Segment[],
        duration: number,
        speakers: Record<string, string>,
    ): Promise<void> {
        const md = this.buildMarkdown(segments, duration, speakers);
        const path = `${this.outputFolder}/${INTERIM_FILENAME}`;
        await this.ensureFolder();

        const existing = this.vault.getAbstractFileByPath(path);
        if (existing) {
            await this.vault.modify(existing as TFile, md);
        } else {
            await this.vault.create(path, md);
        }
    }

    /**
     * Write the final transcript markdown and clean up the interim file.
     */
    async finalize(
        segments: Segment[],
        duration: number,
        speakers: Record<string, string>,
    ): Promise<TFile> {
        const md = this.buildMarkdown(segments, duration, speakers);
        const path = await this.nextAvailablePath();
        await this.ensureFolder();

        const file = await this.vault.create(path, md);

        // Remove interim file if it exists
        const interim = this.vault.getAbstractFileByPath(
            `${this.outputFolder}/${INTERIM_FILENAME}`,
        );
        if (interim) {
            await this.vault.delete(interim);
        }

        return file;
    }

    // ── Private helpers ───────────────────────────────────────

    private appendTranscript(
        lines: string[],
        segments: Segment[],
        speakers: Record<string, string>,
    ): void {
        if (segments.length === 0) return;

        let currentSpeaker = segments[0].speaker_id;
        let groupStart = segments[0].start;
        let groupTexts: string[] = [];

        const flush = () => {
            const name = speakers[currentSpeaker] ?? currentSpeaker;
            const ts = fmtTimestamp(groupStart);
            lines.push(`> **${name}** [${ts}]`);
            lines.push('>');
            for (const t of groupTexts) {
                lines.push(`> ${t}`);
            }
            lines.push('');
        };

        for (const seg of segments) {
            if (seg.speaker_id !== currentSpeaker) {
                flush();
                currentSpeaker = seg.speaker_id;
                groupStart = seg.start;
                groupTexts = [];
            }
            groupTexts.push(seg.text);
        }

        flush();
    }

    /** Return de-duplicated speaker IDs in first-appearance order. */
    private uniqueSpeakers(segments: Segment[]): string[] {
        const seen = new Set<string>();
        const result: string[] = [];
        for (const seg of segments) {
            if (!seen.has(seg.speaker_id)) {
                seen.add(seg.speaker_id);
                result.push(seg.speaker_id);
            }
        }
        return result;
    }

    /** Speaker display names in first-appearance order. */
    private orderedSpeakerNames(
        segments: Segment[],
        speakers: Record<string, string>,
    ): string[] {
        return this.uniqueSpeakers(segments).map(id => speakers[id] ?? id);
    }

    private todayISO(): string {
        const d = new Date();
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    /**
     * Find the next available file path, e.g.:
     *   Meetings/2026-03-08 Meeting.md
     *   Meetings/2026-03-08 Meeting 2.md
     *   Meetings/2026-03-08 Meeting 3.md
     */
    private async nextAvailablePath(): Promise<string> {
        const date = this.todayISO();
        const base = `${this.outputFolder}/${date} Meeting`;
        let candidate = `${base}.md`;

        if (!this.vault.getAbstractFileByPath(candidate)) {
            return candidate;
        }

        let n = 2;
        while (true) {
            candidate = `${base} ${n}.md`;
            if (!this.vault.getAbstractFileByPath(candidate)) {
                return candidate;
            }
            n++;
        }
    }

    /** Ensure the output folder exists in the vault. */
    private async ensureFolder(): Promise<void> {
        const folder = this.vault.getAbstractFileByPath(this.outputFolder);
        if (!folder) {
            await this.vault.createFolder(this.outputFolder);
        }
    }
}

/** Format seconds as MM:SS. */
function fmtTimestamp(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
