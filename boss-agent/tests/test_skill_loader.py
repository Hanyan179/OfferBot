"""SkillLoader 单元测试 — 文件夹格式"""


from agent.skill_loader import SkillInfo, SkillLoader, _parse_frontmatter

# ---------------------------------------------------------------------------
# Helper: 创建文件夹格式的 Skill
# ---------------------------------------------------------------------------

def _make_skill(tmp_path, folder_name: str, content: str):
    """在 tmp_path 下创建 folder_name/SKILL.md"""
    folder = tmp_path / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(content, encoding="utf-8")
    return folder


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
# SkillLoader.load_all — 文件夹格式
# ---------------------------------------------------------------------------

class TestLoadAll:
    def test_empty_directory(self, tmp_path):
        loader = SkillLoader(str(tmp_path))
        assert loader.load_all() == []

    def test_directory_not_exist(self, tmp_path):
        loader = SkillLoader(str(tmp_path / "nonexistent"))
        assert loader.load_all() == []

    def test_multiple_skill_folders_sorted(self, tmp_path):
        _make_skill(tmp_path, "b_skill", "---\nname: B技能\ndescription: B描述\n---\n## 场景描述\nB body")
        _make_skill(tmp_path, "a_skill", "---\nname: A技能\ndescription: A描述\n---\n## 场景描述\nA body")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 2
        assert skills[0].name == "A技能"
        assert skills[1].name == "B技能"

    def test_missing_name_uses_folder_name(self, tmp_path):
        _make_skill(tmp_path, "my-skill", "---\ndescription: 测试\n---\n## 场景描述\n内容")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "my-skill"

    def test_missing_description_uses_first_paragraph(self, tmp_path):
        _make_skill(tmp_path, "plain", "---\nname: Plain\n---\n## 场景描述\n这是第一段文本")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].description == "这是第一段文本"

    def test_loose_md_files_skipped_with_warning(self, tmp_path, caplog):
        """散落的 .md 文件被跳过并记录警告"""
        import logging
        with caplog.at_level(logging.WARNING, logger="agent.skill_loader"):
            (tmp_path / "loose.md").write_text("---\nname: Loose\n---\nbody", encoding="utf-8")
            _make_skill(tmp_path, "real", "---\nname: Real\n---\n## 场景描述\nbody")
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "Real"
        assert "跳过散落的 Skill 文件" in caplog.text

    def test_folder_without_skill_md_skipped(self, tmp_path):
        """无 SKILL.md 的文件夹被跳过（不记录日志）"""
        (tmp_path / "empty_folder").mkdir()
        _make_skill(tmp_path, "valid", "---\nname: Valid\n---\n## 场景描述\nbody")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "Valid"

    def test_skill_fields_populated(self, tmp_path):
        _make_skill(
            tmp_path, "test-skill",
            "---\n"
            "name: 测试技能\n"
            "description: 测试描述\n"
            "when_to_use: 测试场景\n"
            "memory_categories: [a, b]\n"
            "allowed-tools: [tool1]\n"
            "---\n"
            "## 场景描述\nbody content",
        )
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        s = skills[0]
        assert isinstance(s, SkillInfo)
        assert s.name == "测试技能"
        assert s.description == "测试描述"
        assert s.when_to_use == "测试场景"
        assert s.memory_categories == ["a", "b"]
        assert s.allowed_tools == ["tool1"]
        assert s.folder_name == "test-skill"
        assert "body content" in s.body

    def test_malformed_yaml_skill_skipped(self, tmp_path, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger="agent.skill_loader"):
            _make_skill(tmp_path, "bad", "---\n: [invalid\n---\nbody")
            _make_skill(tmp_path, "good", "---\nname: Good\n---\n## 场景描述\nbody")
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
        names = [s.name for s in skills]
        assert "Good" in names
        assert "bad" not in names
        assert "YAML frontmatter 格式无效" in caplog.text

    def test_conditional_skill_with_paths(self, tmp_path):
        _make_skill(
            tmp_path, "conditional",
            "---\nname: Cond\npaths:\n  - 'src/*.py'\n  - 'lib/*'\n---\n## 场景描述\nbody",
        )
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert skills[0].is_conditional is True
        assert skills[0].paths == ["src/*.py", "lib/*"]

    def test_unconditional_skill_without_paths(self, tmp_path):
        _make_skill(tmp_path, "uncond", "---\nname: Uncond\n---\n## 场景描述\nbody")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        assert skills[0].is_conditional is False
        assert skills[0].paths is None


    def test_allowed_tools_unregistered_warning(self, tmp_path, caplog):
        """allowed-tools 引用未注册 Tool 记录警告"""
        import logging

        from agent.tool_registry import ToolRegistry
        registry = ToolRegistry()
        _make_skill(
            tmp_path, "toolcheck",
            "---\nname: TC\nallowed-tools: [nonexistent_tool]\n---\n## 场景描述\nbody",
        )
        with caplog.at_level(logging.WARNING, logger="agent.skill_loader"):
            loader = SkillLoader(str(tmp_path), registry=registry)
            loader.load_all()
        assert "未注册的 Tool" in caplog.text

    def test_missing_scenario_description_warning(self, tmp_path, caplog):
        """正文缺少「场景描述」段落记录警告"""
        import logging
        with caplog.at_level(logging.WARNING, logger="agent.skill_loader"):
            _make_skill(tmp_path, "noscene", "---\nname: NoScene\n---\n这里没有相关段落")
            loader = SkillLoader(str(tmp_path))
            loader.load_all()
        assert "场景描述" in caplog.text


# ---------------------------------------------------------------------------
# SkillLoader.to_prompt_section
# ---------------------------------------------------------------------------

class TestToPromptSection:
    def test_no_skills_returns_empty(self, tmp_path):
        loader = SkillLoader(str(tmp_path))
        assert loader.to_prompt_section() == ""

    def test_output_format(self, tmp_path):
        _make_skill(
            tmp_path, "greet",
            "---\n"
            "name: 模拟打招呼\n"
            "description: 模拟打招呼场景\n"
            "when_to_use: 练习打招呼\n"
            "allowed-tools: [get_memory]\n"
            "---\n## 场景描述\nbody",
        )
        loader = SkillLoader(str(tmp_path))
        section = loader.to_prompt_section()
        assert "## 可用 Skills" in section
        assert "### 模拟打招呼" in section
        assert "模拟打招呼场景" in section
        assert "适用场景: 练习打招呼" in section
        assert "get_skill_content" in section

    def test_multiple_skills_in_section(self, tmp_path):
        _make_skill(tmp_path, "a", "---\nname: A\ndescription: DA\n---\n## 场景描述\n")
        _make_skill(tmp_path, "b", "---\nname: B\ndescription: DB\n---\n## 场景描述\n")
        loader = SkillLoader(str(tmp_path))
        section = loader.to_prompt_section()
        assert "### A" in section
        assert "### B" in section
        assert "DA" in section
        assert "DB" in section

    def test_conditional_skill_filtering(self, tmp_path):
        """Unconditional 始终显示，Conditional 按 activated_skills 过滤"""
        _make_skill(tmp_path, "always", "---\nname: Always\ndescription: D1\n---\n## 场景描述\n")
        _make_skill(
            tmp_path, "cond",
            "---\nname: Cond\ndescription: D2\npaths:\n  - 'src/*'\n---\n## 场景描述\n",
        )
        loader = SkillLoader(str(tmp_path))
        loader.load_all()

        # 未激活时：Cond 仅显示名称和激活条件
        section = loader.to_prompt_section()
        assert "### Always" in section
        assert "D1" in section
        assert "[条件激活: 未激活]" in section

        # 激活后：Cond 显示完整摘要
        section_activated = loader.to_prompt_section(activated_skills={"Cond"})
        assert "### Cond" in section_activated
        assert "D2" in section_activated
        assert "[条件激活: 未激活]" not in section_activated

    def test_prompt_section_contains_usage_guide(self, tmp_path):
        """to_prompt_section 包含使用指引文本"""
        _make_skill(tmp_path, "s", "---\nname: S\n---\n## 场景描述\n")
        loader = SkillLoader(str(tmp_path))
        section = loader.to_prompt_section()
        assert "get_skill_content" in section
        assert "场景参考规范" in section


# ---------------------------------------------------------------------------
# SkillLoader.get_skill_content
# ---------------------------------------------------------------------------

class TestGetSkillContent:
    def test_match_by_frontmatter_name(self, tmp_path):
        _make_skill(tmp_path, "greet", "---\nname: 模拟打招呼\n---\n## 场景描述\n内容")
        loader = SkillLoader(str(tmp_path))
        result = loader.get_skill_content("模拟打招呼")
        assert result is not None
        assert result["name"] == "模拟打招呼"
        assert "内容" in result["content"]
        assert isinstance(result["allowed_tools"], list)

    def test_match_by_folder_name(self, tmp_path):
        _make_skill(tmp_path, "greet", "---\nname: 其他名字\n---\n## 场景描述\nbody")
        loader = SkillLoader(str(tmp_path))
        result = loader.get_skill_content("greet")
        assert result is not None
        assert result["name"] == "其他名字"

    def test_no_match_returns_none(self, tmp_path):
        _make_skill(tmp_path, "greet", "---\nname: 打招呼\n---\n## 场景描述\n")
        loader = SkillLoader(str(tmp_path))
        assert loader.get_skill_content("不存在的技能") is None

    def test_directory_not_exist_returns_none(self, tmp_path):
        loader = SkillLoader(str(tmp_path / "nonexistent"))
        assert loader.get_skill_content("any") is None

    def test_skill_dir_variable_replaced(self, tmp_path):
        """${SKILL_DIR} 变量替换正确执行"""
        _make_skill(
            tmp_path, "myskill",
            "---\nname: MySkill\n---\n## 场景描述\n路径: ${SKILL_DIR}/template.txt",
        )
        loader = SkillLoader(str(tmp_path))
        result = loader.get_skill_content("MySkill")
        assert result is not None
        assert "${SKILL_DIR}" not in result["content"]
        assert str((tmp_path / "myskill").resolve()) in result["content"]

    def test_returns_dict_with_all_fields(self, tmp_path):
        """get_skill_content 返回字典格式（含 content/allowed_tools/name/description）"""
        _make_skill(
            tmp_path, "full",
            "---\nname: Full\ndescription: Desc\nallowed-tools: [t1, t2]\n---\n## 场景描述\nbody",
        )
        loader = SkillLoader(str(tmp_path))
        result = loader.get_skill_content("Full")
        assert result is not None
        assert set(result.keys()) == {"content", "allowed_tools", "name", "description"}
        assert result["name"] == "Full"
        assert result["description"] == "Desc"
        assert result["allowed_tools"] == ["t1", "t2"]


# ---------------------------------------------------------------------------
# SkillLoader.get_all_skill_names
# ---------------------------------------------------------------------------

class TestGetAllSkillNames:
    def test_returns_all_names(self, tmp_path):
        _make_skill(tmp_path, "a", "---\nname: Alpha\n---\n## 场景描述\n")
        _make_skill(tmp_path, "b", "---\nname: Beta\n---\n## 场景描述\n")
        loader = SkillLoader(str(tmp_path))
        names = loader.get_all_skill_names()
        assert set(names) == {"Alpha", "Beta"}

    def test_empty_returns_empty(self, tmp_path):
        loader = SkillLoader(str(tmp_path))
        assert loader.get_all_skill_names() == []


# ---------------------------------------------------------------------------
# Error tolerance — 文件夹格式
# ---------------------------------------------------------------------------

class TestErrorTolerance:
    def test_unreadable_skill_md_skipped(self, tmp_path):
        """SKILL.md 无法读取时跳过该文件夹"""
        bad_folder = tmp_path / "bad"
        bad_folder.mkdir()
        skill_md = bad_folder / "SKILL.md"
        skill_md.mkdir()  # directory instead of file → read_text will raise

        _make_skill(tmp_path, "good", "---\nname: Good\n---\n## 场景描述\nbody")
        loader = SkillLoader(str(tmp_path))
        skills = loader.load_all()
        names = [s.name for s in skills]
        assert "Good" in names
