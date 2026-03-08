import { App, PluginSettingTab, Setting } from "obsidian";
import type MeetingScribePlugin from "./main";

export interface MeetingScribeSettings {
    serverUrl: string;
    outputFolder: string;
    autoStart: boolean;
    whisperModel: string;
}

export const DEFAULT_SETTINGS: MeetingScribeSettings = {
    serverUrl: "ws://localhost:9876",
    outputFolder: "Meetings",
    autoStart: false,
    whisperModel: "base",
};

export class MeetingScribeSettingTab extends PluginSettingTab {
    plugin: MeetingScribePlugin;

    constructor(app: App, plugin: MeetingScribePlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();

        new Setting(containerEl)
            .setName("Server URL")
            .setDesc("WebSocket URL of the transcription server")
            .addText((text) =>
                text
                    .setPlaceholder("ws://localhost:9876")
                    .setValue(this.plugin.settings.serverUrl)
                    .onChange(async (value) => {
                        this.plugin.settings.serverUrl = value;
                        await this.plugin.saveSettings();
                    })
            );

        new Setting(containerEl)
            .setName("Output folder")
            .setDesc("Vault folder where meeting transcripts are saved")
            .addText((text) =>
                text
                    .setPlaceholder("Meetings")
                    .setValue(this.plugin.settings.outputFolder)
                    .onChange(async (value) => {
                        this.plugin.settings.outputFolder = value;
                        await this.plugin.saveSettings();
                    })
            );

        new Setting(containerEl)
            .setName("Auto-start")
            .setDesc("Automatically connect to the server when the plugin loads")
            .addToggle((toggle) =>
                toggle
                    .setValue(this.plugin.settings.autoStart)
                    .onChange(async (value) => {
                        this.plugin.settings.autoStart = value;
                        await this.plugin.saveSettings();
                    })
            );

        new Setting(containerEl)
            .setName("Whisper model")
            .setDesc("Model size passed to the transcription server on start")
            .addDropdown((dropdown) =>
                dropdown
                    .addOptions({
                        tiny: "tiny",
                        base: "base",
                        small: "small",
                        medium: "medium",
                        large: "large",
                    })
                    .setValue(this.plugin.settings.whisperModel)
                    .onChange(async (value) => {
                        this.plugin.settings.whisperModel = value;
                        await this.plugin.saveSettings();
                    })
            );
    }
}
