"""SkillLoader 单元测试"""

import pytest

from agent.skill_loader import SkillLoader, _parse_frontmatter


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = (
            "---\n"
            "name: 模拟打招呼\n"
            "description: 模拟 Boss 直聘打招呼场景\n"
            "when_to_use: 当用户想要练习打招呼话术时\n"
            "memory_categories: [language_style, communication_preferences]\n"
            "allowed-tools: [get_memory, search_memory]\n"
            "---\n"
            "\n## 场景描述\n\n测试内容"
        )
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "模拟打招呼"
        assert fm["description"] == "模拟 Boss 直聘打招呼场景"
        assert fm["when_to_use"] == "当用户想要练习打招呼话术时"
        assert fm["memory_categories"] == ["language_style", "communication_preferences"]
        assert fm["allowed-tools"] == ["get_memory", "search_memory"]
        assert "场景描述" in body
        assert "测试内容" in body

    def test_no_frontmatter(self):
        content = "# 普通 Markdown\n\n没有 frontmatter"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_invalid_yaml(self):
        content = "---\n: invalid: [yaml\n---\nbody"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_frontmatter_not_dict(self):
        content = "---\njust a string\n---\nbody text"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_incomplete_delimiters(self):
        """Only one --- delimiter, no closing."""
        content = "---\nname: test\nno closing delimiter"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_empty_frontmatter(self):
        content = "---\n---\nbody"
        fm, body = _parse_frontmatter(content)
        # yaml.safe_load("") returns None, which is not a dict
        assert fm == {}
        assert body == content


# ---------------------------------------------------------------------------
# SkillLoader.load_all
# ---------------------------------------------------------------------------

class TestLoadAll:
    def test_empty_directory(self, tmp_path):
        loader = SkillLoader(str(tmp_path))
        assert loader.load_all() == []

    def test_directory_not_exist(self, tmp_path):
        loader = SkillLoader(str(tmp_path / "nonexistent"))
        assert loader.load_all() == []

    def test_multiple_md_files_sorted(self, tmp_path):
        (tmp_path / "b_skill.md").write_text(
            "---\nname: B技能\ndescription: B描述\n---\nB body",
            encoding="utf-8",
        )
        (tmp_path / "a_skill.md").write_text(
            "---\nname: A技能\ndescription: A描述\n---\nA body",
            encoding="utf-8",
        )
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 2
        assert skills[0]["name"] == "A技能"
        assert skills[1]["name"] == "B技能"

    def test_missing_frontmatter_fields_use_defaults(self, tmp_path):
        (tmp_path / "plain.md").write_text("# 纯 Markdown\n无 frontmatter", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        s = skills[0]
        assert s["name"] == "plain"  # stem as name
        assert s["description"] == ""
        assert s["when_to_use"] == ""
        assert s["memory_categories"] == []
        assert s["allowed_tools"] == []

    def test_non_md_files_ignored(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a skill", encoding="utf-8")
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        (tmp_path / "real.md").write_text("---\nname: Real\n---\nbody", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0]["name"] == "Real"

    def test_skill_fields_populated(self, tmp_path):
        (tmp_path / "test.md").write_text(
            "---\n"
            "name: 测试技能\n"
            "description: 测试描述\n"
            "when_to_use: 测试场景\n"
            "memory_categories: [a, b]\n"
            "allowed-tools: [tool1]\n"
            "---\n"
            "body content",
            encoding="utf-8",
        )
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        s = skills[0]
        assert s["name"] == "测试技能"
        assert s["description"] == "测试描述"
        assert s["when_to_use"] == "测试场景"
        assert s["memory_categories"] == ["a", "b"]
        assert s["allowed_tools"] == ["tool1"]
        assert s["file"] == "test.md"
        assert s["body"] == "body content"

    def test_malformed_yaml_skill_skipped(self, tmp_path):
        (tmp_path / "bad.md").write_text("---\n: [invalid\n---\nbody", encoding="utf-8")
        (tmp_path / "good.md").write_text("---\nname: Good\n---\nbody", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        # bad.md has invalid YAML → _parse_frontmatter returns ({}, content)
        # load_all still includes it with defaults (stem as name)
        assert any(s["name"] == "Good" for s in skills)


# ---------------------------------------------------------------------------
# SkillLoader.to_prompt_section
# ---------------------------------------------------------------------------

class TestToPromptSection:
    def test_no_skills_returns_empty(self, tmp_path):
        loader = SkillLoader(str(tmp_path))
        assert loader.to_prompt_section() == ""

    def test_output_format(self, tmp_path):
        (tmp_path / "greet.md").write_text(
            "---\n"
            "name: 模拟打招呼\n"
            "description: 模拟打招呼场景\n"
            "when_to_use: 练习打招呼\n"
            "---\nbody",
            encoding="utf-8",
        )
        loader = SkillLoader(str(tmp_path))
        section = loader.to_prompt_section()
        assert "## 可用 Skills" in section
        assert "### 模拟打招呼" in section
        assert "模拟打招呼场景" in section
        assert "适用场景: 练习打招呼" in section

    def test_multiple_skills_in_section(self, tmp_path):
        (tmp_path / "a.md").write_text("---\nname: A\ndescription: DA\n---\n", encoding="utf-8")
        (tmp_path / "b.md").write_text("---\nname: B\ndescription: DB\n---\n", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        section = loader.to_prompt_section()
        assert "### A" in section
        assert "### B" in section
        assert "DA" in section
        assert "DB" in section


# ---------------------------------------------------------------------------
# SkillLoader.get_skill_content
# ---------------------------------------------------------------------------

class TestGetSkillContent:
    def test_match_by_frontmatter_name(self, tmp_path):
        content = "---\nname: 模拟打招呼\n---\n## 场景\n内容"
        (tmp_path / "greet.md").write_text(content, encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        result = loader.get_skill_content("模拟打招呼")
        assert result == content

    def test_match_by_file_stem(self, tmp_path):
        content = "---\nname: 其他名字\n---\nbody"
        (tmp_path / "greet.md").write_text(content, encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        result = loader.get_skill_content("greet")
        assert result == content

    def test_no_match_returns_none(self, tmp_path):
        (tmp_path / "greet.md").write_text("---\nname: 打招呼\n---\n", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        assert loader.get_skill_content("不存在的技能") is None

    def test_directory_not_exist_returns_none(self, tmp_path):
        loader = SkillLoader(str(tmp_path / "nonexistent"))
        assert loader.get_skill_content("any") is None


# ---------------------------------------------------------------------------
# Error tolerance
# ---------------------------------------------------------------------------

class TestErrorTolerance:
    def test_unreadable_file_skipped_in_load_all(self, tmp_path):
        """A file that raises on read_text should be skipped."""
        bad = tmp_path / "bad.md"
        bad.mkdir()  # directory, not a file → read_text will raise
        (tmp_path / "good.md").write_text("---\nname: Good\n---\nbody", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        names = [s["name"] for s in skills]
        assert "Good" in names

    def test_unreadable_file_skipped_in_get_skill_content(self, tmp_path):
        """get_skill_content should skip files that can't be read."""
        bad = tmp_path / "bad.md"
        bad.mkdir()
        (tmp_path / "good.md").write_text("---\nname: Good\n---\nbody", encoding="utf-8")
        loader = SkillLoader(str(tmp_path))
        assert loader.get_skill_content("Good") is not None
