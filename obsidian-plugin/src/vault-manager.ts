import { Vault, TFile, TFolder } from 'obsidian';
import type { Segment, ActionItem, AssistantTopicChange } from './types';

/**
 * Manages the Meeting Scribe vault folder structure and note CRUD.
 *
 * Folder layout:
 *   <rootFolder>/
 *     meetings/   — session summaries and minutes
 *     topics/     — one note per detected topic
 *     actions/    — action items tracker
 */
export class VaultManager {
    private vault: Vault;
    private rootFolder: string;

    constructor(vault: Vault, rootFolder: string) {
        this.vault = vault;
        this.rootFolder = rootFolder.replace(/\/+$/, '');
    }

    /** Update root folder path (e.g., from settings change). */
    setRootFolder(folder: string): void {
        this.rootFolder = folder.replace(/\/+$/, '');
    }

    // ── Folder paths ──────────────────────────────────────

    get meetingsPath(): string { return `${this.rootFolder}/meetings`; }
    get topicsPath(): string { return `${this.rootFolder}/topics`; }
    get actionsPath(): string { return `${this.rootFolder}/actions`; }

    // ── Folder setup ──────────────────────────────────────

    /** Ensure the full folder structure exists. */
    async ensureFolders(): Promise<void> {
        await this.ensureFolder(this.rootFolder);
        await this.ensureFolder(this.meetingsPath);
        await this.ensureFolder(this.topicsPath);
        await this.ensureFolder(this.actionsPath);
    }

    private async ensureFolder(path: string): Promise<void> {
        try {
            const existing = this.vault.getAbstractFileByPath(path);
            if (!existing) {
                await this.vault.createFolder(path);
            }
        } catch {
            // Folder may already exist
        }
    }

    // ── Meeting notes ─────────────────────────────────────

    /** Write an interim (crash-recovery) file in the meetings folder. */
    async writeInterimMeeting(
        segments: Segment[],
        duration: number,
        speakers: Record<string, string>,
        summary?: string,
    ): Promise<void> {
        await this.ensureFolders();
        const md = this.buildMeetingMarkdown(segments, duration, speakers, summary, true);
        const path = `${this.meetingsPath}/.meeting-scribe-interim.md`;

        const existing = this.vault.getAbstractFileByPath(path);
        if (existing) {
            await this.vault.modify(existing as TFile, md);
        } else {
            await this.vault.create(path, md);
        }
    }

    /** Finalize a meeting — write permanent note and clean up interim. */
    async finalizeMeeting(
        segments: Segment[],
        duration: number,
        speakers: Record<string, string>,
        summary?: string,
        actionItems?: ActionItem[],
        topics?: string[],
    ): Promise<TFile> {
        await this.ensureFolders();
        const md = this.buildMeetingMarkdown(segments, duration, speakers, summary, false, actionItems, topics);
        const path = await this.nextAvailablePath(this.meetingsPath, 'Meeting');

        const file = await this.vault.create(path, md);

        // Clean up interim
        const interim = this.vault.getAbstractFileByPath(
            `${this.meetingsPath}/.meeting-scribe-interim.md`
        );
        if (interim) {
            await this.vault.delete(interim);
        }

        return file;
    }

    private buildMeetingMarkdown(
        segments: Segment[],
        duration: number,
        speakers: Record<string, string>,
        summary?: string,
        isInterim = false,
        actionItems?: ActionItem[],
        topics?: string[],
    ): string {
        const date = todayISO();
        const lines: string[] = [];

        // Frontmatter
        lines.push('---');
        lines.push(`date: ${date}`);
        lines.push(`duration: ${fmtTime(duration)}`);
        if (isInterim) lines.push('status: recording');
        lines.push('speakers:');
        for (const name of this.orderedSpeakerNames(segments, speakers)) {
            lines.push(`  - ${name}`);
        }
        if (topics && topics.length > 0) {
            lines.push('topics:');
            for (const t of topics) {
                lines.push(`  - "${t}"`);
            }
        }
        lines.push('---');
        lines.push('');

        // Summary section
        if (summary) {
            lines.push('## Summary');
            lines.push('');
            lines.push(summary);
            lines.push('');
        }

        // Action items section
        if (actionItems && actionItems.length > 0) {
            lines.push('## Action Items');
            lines.push('');
            for (const item of actionItems) {
                const assignee = item.assignee ? ` (@${item.assignee})` : '';
                lines.push(`- [ ] ${item.text}${assignee}`);
            }
            lines.push('');
        }

        // Speakers
        lines.push('## Speakers');
        lines.push('');
        for (const name of this.orderedSpeakerNames(segments, speakers)) {
            lines.push(`- **${name}**`);
        }
        lines.push('');

        // Transcript
        lines.push('## Transcript');
        lines.push('');
        this.appendTranscript(lines, segments, speakers);

        return lines.join('\n') + '\n';
    }

    // ── Topic notes ───────────────────────────────────────

    /** Create or update a topic note. */
    async upsertTopicNote(
        topicName: string,
        context: string,
        meetingDate?: string,
    ): Promise<TFile> {
        await this.ensureFolders();
        const safeName = this.sanitizeFilename(topicName);
        const path = `${this.topicsPath}/${safeName}.md`;

        const existing = this.vault.getAbstractFileByPath(path);
        if (existing) {
            // Append new context to existing topic note
            const file = existing as TFile;
            const currentContent = await this.vault.read(file);
            const entry = `\n### ${meetingDate || todayISO()}\n\n${context}\n`;
            await this.vault.modify(file, currentContent + entry);
            return file;
        } else {
            // Create new topic note
            const lines: string[] = [];
            lines.push('---');
            lines.push(`topic: "${topicName}"`);
            lines.push(`created: ${todayISO()}`);
            lines.push(`last_updated: ${todayISO()}`);
            lines.push('---');
            lines.push('');
            lines.push(`# ${topicName}`);
            lines.push('');
            lines.push(`### ${meetingDate || todayISO()}`);
            lines.push('');
            lines.push(context);
            lines.push('');

            return await this.vault.create(path, lines.join('\n'));
        }
    }

    // ── Action items tracker ──────────────────────────────

    /** Update the action items tracker note. */
    async updateActionTracker(
        items: ActionItem[],
        meetingDate?: string,
    ): Promise<TFile> {
        await this.ensureFolders();
        const path = `${this.actionsPath}/Action Items.md`;
        const date = meetingDate || todayISO();

        const existing = this.vault.getAbstractFileByPath(path);
        if (existing) {
            const file = existing as TFile;
            const currentContent = await this.vault.read(file);

            // Append new items under a date header
            const newEntries: string[] = [];
            newEntries.push(`\n## ${date}\n`);
            for (const item of items) {
                const assignee = item.assignee ? ` (@${item.assignee})` : '';
                newEntries.push(`- [ ] ${item.text}${assignee}`);
            }
            newEntries.push('');

            await this.vault.modify(file, currentContent + newEntries.join('\n'));
            return file;
        } else {
            // Create new tracker
            const lines: string[] = [];
            lines.push('---');
            lines.push(`created: ${todayISO()}`);
            lines.push('---');
            lines.push('');
            lines.push('# Action Items');
            lines.push('');
            lines.push(`## ${date}`);
            lines.push('');
            for (const item of items) {
                const assignee = item.assignee ? ` (@${item.assignee})` : '';
                lines.push(`- [ ] ${item.text}${assignee}`);
            }
            lines.push('');

            return await this.vault.create(path, lines.join('\n'));
        }
    }

    // ── Shared helpers ────────────────────────────────────

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
            const ts = fmtTime(groupStart);
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

    private uniqueSpeakers(segments: Segment[]): string[] {
        const seen = new Set<string>();
        const result: string[] = [];
        for (const seg of segments) {
            const id = seg.speaker_id ?? 'Unknown';
            if (!seen.has(id)) {
                seen.add(id);
                result.push(id);
            }
        }
        return result;
    }

    private orderedSpeakerNames(
        segments: Segment[],
        speakers: Record<string, string>,
    ): string[] {
        return this.uniqueSpeakers(segments).map(id => speakers[id] ?? id);
    }

    private async nextAvailablePath(folder: string, prefix: string): Promise<string> {
        const date = todayISO();
        const base = `${folder}/${date} ${prefix}`;
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

    private sanitizeFilename(name: string): string {
        // Remove characters not allowed in filenames
        return name
            .replace(/[\\/:*?"<>|]/g, '')
            .replace(/\s+/g, ' ')
            .trim()
            .substring(0, 100);
    }
}

function todayISO(): string {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function fmtTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
