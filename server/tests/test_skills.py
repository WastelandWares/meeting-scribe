"""Tests for the skills loader."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.skills import Skill, SkillsConfig, SkillsLoader, BUILTIN_SKILLS_DIR


class TestSkill:
    def test_to_dict(self):
        skill = Skill(name="test", content="# Test", source="builtin", path="/tmp/test.md")
        d = skill.to_dict()
        assert d["name"] == "test"
        assert d["source"] == "builtin"


class TestSkillsLoader:
    def test_load_builtin_skills(self):
        loader = SkillsLoader()
        skills = loader.load()
        assert len(skills) >= 2
        names = [s.name for s in skills]
        assert "summarizer" in names
        assert "action-tracker" in names

    def test_builtin_skills_have_content(self):
        loader = SkillsLoader()
        skills = loader.load()
        for skill in skills:
            assert len(skill.content) > 50
            assert skill.source == "builtin"

    def test_load_user_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a user skill
            skill_path = Path(tmpdir) / "custom.md"
            skill_path.write_text("# Custom Skill\nDo something custom.")

            config = SkillsConfig(user_skills_path=tmpdir)
            loader = SkillsLoader(config)
            skills = loader.load()

            user_skills = [s for s in skills if s.source == "user"]
            assert len(user_skills) == 1
            assert user_skills[0].name == "custom"

    def test_disabled_returns_empty(self):
        config = SkillsConfig(enabled=False)
        loader = SkillsLoader(config)
        skills = loader.load()
        assert skills == []

    def test_nonexistent_user_path(self):
        config = SkillsConfig(user_skills_path="/nonexistent/path")
        loader = SkillsLoader(config)
        skills = loader.load()
        # Should still load builtins
        assert len(skills) >= 2

    def test_get_system_prompt_addition(self):
        loader = SkillsLoader()
        loader.load()
        addition = loader.get_system_prompt_addition()
        assert "Active Skills" in addition
        assert "summarizer" in addition
        assert "action-tracker" in addition

    def test_get_system_prompt_addition_empty(self):
        config = SkillsConfig(enabled=False)
        loader = SkillsLoader(config)
        loader.load()
        assert loader.get_system_prompt_addition() == ""

    def test_empty_skill_file_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_path = Path(tmpdir) / "empty.md"
            empty_path.write_text("")

            config = SkillsConfig(user_skills_path=tmpdir)
            loader = SkillsLoader(config)
            skills = loader.load()

            user_skills = [s for s in skills if s.source == "user"]
            assert len(user_skills) == 0

    def test_get_skills_info(self):
        loader = SkillsLoader()
        loader.load()
        info = loader.get_skills_info()
        assert len(info) >= 2
        assert all("name" in s for s in info)
        assert all("source" in s for s in info)


class TestBuiltinSkillsExist:
    def test_skills_directory_exists(self):
        assert BUILTIN_SKILLS_DIR.exists()

    def test_summarizer_exists(self):
        assert (BUILTIN_SKILLS_DIR / "summarizer.md").exists()

    def test_action_tracker_exists(self):
        assert (BUILTIN_SKILLS_DIR / "action-tracker.md").exists()
