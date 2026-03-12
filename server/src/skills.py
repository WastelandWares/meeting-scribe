"""Skills loader for the meeting assistant.

Skills are markdown files containing instructions that augment the assistant's
system prompt. Built-in skills ship with the server; user skills can be loaded
from a configurable path (e.g., an Obsidian vault folder).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Built-in skills directory (relative to this file's parent)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class Skill:
    """A loaded skill with its metadata and content."""

    name: str
    content: str
    source: str  # "builtin" or "user"
    path: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "path": self.path,
        }


@dataclass
class SkillsConfig:
    """Configuration for the skills system."""

    enabled: bool = True
    user_skills_path: Optional[str] = None  # Path to user skills directory


class SkillsLoader:
    """Loads and manages assistant skills from markdown files.

    Skills are loaded at startup and their content is included in the
    assistant's system prompt to guide its behavior.
    """

    def __init__(self, config: Optional[SkillsConfig] = None) -> None:
        self._config = config or SkillsConfig()
        self._skills: list[Skill] = []

    def load(self) -> list[Skill]:
        """Load all skills (built-in + user). Returns the loaded skills."""
        self._skills = []

        if not self._config.enabled:
            logger.info("Skills system disabled")
            return self._skills

        # Load built-in skills
        self._load_from_directory(BUILTIN_SKILLS_DIR, source="builtin")

        # Load user skills if path is configured
        if self._config.user_skills_path:
            user_path = Path(self._config.user_skills_path)
            if user_path.exists() and user_path.is_dir():
                self._load_from_directory(user_path, source="user")
            else:
                logger.warning("User skills path does not exist: %s", user_path)

        logger.info(
            "Loaded %d skills (%d builtin, %d user)",
            len(self._skills),
            sum(1 for s in self._skills if s.source == "builtin"),
            sum(1 for s in self._skills if s.source == "user"),
        )
        return self._skills

    def _load_from_directory(self, directory: Path, source: str) -> None:
        """Load all .md files from a directory as skills."""
        if not directory.exists():
            logger.debug("Skills directory does not exist: %s", directory)
            return

        for filepath in sorted(directory.glob("*.md")):
            try:
                content = filepath.read_text(encoding="utf-8").strip()
                if not content:
                    logger.warning("Empty skill file: %s", filepath)
                    continue

                name = filepath.stem  # filename without .md
                skill = Skill(
                    name=name,
                    content=content,
                    source=source,
                    path=str(filepath),
                )
                self._skills.append(skill)
                logger.debug("Loaded skill: %s (%s)", name, source)

            except Exception as e:
                logger.error("Failed to load skill %s: %s", filepath, e)

    @property
    def skills(self) -> list[Skill]:
        """Return all loaded skills."""
        return list(self._skills)

    def get_system_prompt_addition(self) -> str:
        """Build the skills section to append to the assistant's system prompt."""
        if not self._skills:
            return ""

        parts = ["\n\n--- Active Skills ---\n"]
        for skill in self._skills:
            parts.append(f"\n### {skill.name} ({skill.source})\n")
            parts.append(skill.content)
            parts.append("")

        return "\n".join(parts)

    def get_skills_info(self) -> list[dict]:
        """Return skill metadata for server_info broadcast."""
        return [s.to_dict() for s in self._skills]
