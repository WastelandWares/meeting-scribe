import { Vault } from 'obsidian';

const CONFIG_FILE = '.meeting-scribe.json';

interface SpeakerConfig {
    speakers: Record<string, string>;
}

/**
 * Persistent speaker label store backed by `.meeting-scribe.json` in the vault root.
 *
 * Maps raw speaker IDs (e.g. "SPEAKER_00") to human-readable names (e.g. "Thomas").
 */
export class SpeakerStore {
    private labels: Map<string, string> = new Map();

    /**
     * Return the display label for a speaker.
     * Falls back to the raw speakerId if no label has been assigned.
     */
    getLabel(speakerId: string): string {
        return this.labels.get(speakerId) ?? speakerId;
    }

    /** Assign a human-readable name to a speaker ID. */
    setLabel(speakerId: string, name: string): void {
        this.labels.set(speakerId, name);
    }

    /** Return a plain object of all speaker-id → name mappings. */
    getAllLabels(): Record<string, string> {
        return Object.fromEntries(this.labels);
    }

    /** Load speaker labels from the vault config file. */
    async loadFromVault(vault: Vault): Promise<void> {
        const file = vault.getAbstractFileByPath(CONFIG_FILE);
        if (!file) {
            this.labels = new Map();
            return;
        }

        try {
            const raw = await vault.read(file as import('obsidian').TFile);
            const config: SpeakerConfig = JSON.parse(raw);
            this.labels = new Map(Object.entries(config.speakers ?? {}));
        } catch (e) {
            console.error('[meeting-scribe] Failed to read speaker config:', e);
            this.labels = new Map();
        }
    }

    /** Persist current speaker labels to the vault config file. */
    async saveToVault(vault: Vault): Promise<void> {
        const config: SpeakerConfig = {
            speakers: this.getAllLabels(),
        };
        const content = JSON.stringify(config, null, 2) + '\n';

        const file = vault.getAbstractFileByPath(CONFIG_FILE);
        if (file) {
            await vault.modify(file as import('obsidian').TFile, content);
        } else {
            await vault.create(CONFIG_FILE, content);
        }
    }
}
