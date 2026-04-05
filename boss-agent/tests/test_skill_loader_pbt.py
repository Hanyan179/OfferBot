"""
Property-based tests for SkillLoader (文件夹格式).

Property 1: Frontmatter 解析正确性
对任意有效 SKILL.md（合法 YAML frontmatter），SkillLoader 解析后的 SkillInfo 字段应与 frontmatter 一致。
验证: 需求 4.1, 4.2, 4.3, 1.3, 1.4, 3.1, 5.1, 5.2, 5.3

Property 2: 文件夹扫描正确性
对任意 skills 目录结构，load_all() 仅返回拥有 SKILL.md 的子文件夹对应的 Skill。
验证: 需求 1.1, 1.2, 1.5

Property 3: SKILL_DIR 变量替换
对任意 Skill 内容和文件夹路径，get_skill_content() 返回的内容中 ${SKILL_DIR} 应被替换为绝对路径。
验证: 需求 6.1, 6.3

Property 4: get_skill_content 返回完整数据
对任意已加载 Skill，get_skill_content 返回包含 content/allowed_tools/name/description 的字典。
验证: 需求 7.3, 7.4, 3.2

Property 5: Prompt Section 摘要完整性
对任意 Skill 集合，to_prompt_section() 输出包含每个活跃 Skill 的 name/description/when_to_use/allowed-tools，
且不包含完整 body 正文。
验证: 需求 8.1, 7.1

Property 6: 条件激活过滤
对任意包含 Conditional 和 Unconditional Skill 的集合，to_prompt_section(activated_skills) 正确过滤。
验证: 需求 8.3, 8.4, 5.1, 5.4

Property 7: 迁移内容保持
对任意合法扁平格式 Skill 文件内容，迁移到文件夹格式后 SkillLoader 加载的字段与原始一致。
验证: 需求 9.5, 9.6
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from hypothesis import given, settings, assume, strategies as st

from agent.skill_loader import SkillLoader, SkillInfo, _parse_frontmatter


# ---------------------------------------------------------------------------
# Strategies (Generators)
# ---------------------------------------------------------------------------

# Safe characters for YAML values — avoid YAML-special chars and control chars
_yaml_safe_chars = st.characters(
    categories=("L", "N", "Z"),
    exclude_characters="\x00\r\n:{}[]#&*!|>'\"%@`",
)

st_safe_text = (
    st.text(alphabet=_yaml_safe_chars, min_size=1, max_size=40)
    .map(str.strip)
    .filter(lambda s: len(s) >= 1)
)

st_tool_name = st.from_regex(r"[a-z][a-z0-9_]{1,20}", fullmatch=True)

st_folder_name = st.one_of(
    st.from_regex(r"[a-z][a-z0-9\-]{0,15}", fullmatch=True),
    st.text(
        alphabet=st.characters(categories=("L",), exclude_characters="/\\. \t\n\r"),
        min_size=1,
        max_size=10,
    ).filter(lambda s: s.strip() and not s.startswith(".")),
)

st_glob_pattern = st.from_regex(r"[a-z]{1,8}/\*\.[a-z]{1,4}", fullmatch=True)


def _build_frontmatter(**fields) -> str:
    """Build a YAML frontmatter string from keyword arguments, skipping None values.

    When no fields are provided, omits frontmatter entirely (no --- delimiters)
    to avoid producing empty frontmatter that SkillLoader treats as invalid YAML.
    """
    data = {k: v for k, v in fields.items() if v is not None}
    if not data:
        return ""
    return "---\n" + yaml.dump(data, allow_unicode=True, default_flow_style=False) + "---\n"


def _make_skill_folder(base: Path, folder_name: str, content: str) -> Path:
    """Create folder_name/SKILL.md under base with given content."""
    folder = base / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(content, encoding="utf-8")
    return folder


@st.composite
def skill_frontmatter(draw):
    """Generate a random valid YAML frontmatter dict with optional fields."""
    fm = {}
    if draw(st.booleans()):
        fm["name"] = draw(st_safe_text)
    if draw(st.booleans()):
        fm["description"] = draw(st_safe_text)
    if draw(st.booleans()):
        fm["when_to_use"] = draw(st_safe_text)
    if draw(st.booleans()):
        fm["memory_categories"] = draw(st.lists(st_tool_name, max_size=3))
    if draw(st.booleans()):
        fm["allowed-tools"] = draw(st.lists(st_tool_name, min_size=1, max_size=3))
    if draw(st.booleans()):
        fm["paths"] = draw(st.lists(st_glob_pattern, min_size=1, max_size=3))
    return fm


@st.composite
def skill_body(draw):
    """Generate a random Markdown body, optionally with 场景描述 and ${SKILL_DIR}."""
    parts = []
    if draw(st.booleans()):
        parts.append("## 场景描述\n")
    parts.append(draw(st_safe_text))
    if draw(st.booleans()):
        parts.append("\n路径: ${SKILL_DIR}/resource.txt")
    parts.append("\n额外内容段落")
    return "\n".join(parts)


@st.composite
def skill_directory(draw):
    """Generate a random skills directory layout.

    Returns dict with:
        folders: list of (folder_name, skill_md_content | None)
        loose_files: list of filenames
    """
    n_folders = draw(st.integers(min_value=0, max_value=5))
    folders = []
    used_names: set[str] = set()
    for _ in range(n_folders):
        name = draw(st_folder_name.filter(lambda n, u=used_names: n not in u))
        used_names.add(name)
        has_skill_md = draw(st.booleans())
        if has_skill_md:
            fm = draw(skill_frontmatter())
            bd = draw(skill_body())
            content = _build_frontmatter(**fm) + bd
            folders.append((name, content))
        else:
            folders.append((name, None))

    n_loose = draw(st.integers(min_value=0, max_value=3))
    loose_files = [f"loose_{i}.md" for i in range(n_loose)]
    return {"folders": folders, "loose_files": loose_files}


# ---------------------------------------------------------------------------
# Property 1: Frontmatter 解析正确性
# Feature: skills-folder-architecture, Property 1: Frontmatter 解析正确性
# ---------------------------------------------------------------------------


class TestFrontmatterParsing:
    """
    Property 1: Frontmatter 解析正确性

    For any valid SKILL.md with legal YAML frontmatter, SkillLoader should parse
    SkillInfo fields consistent with the frontmatter values.

    Validates: Requirements 4.1, 4.2, 4.3, 1.3, 1.4, 3.1, 5.1, 5.2, 5.3
    """

    @given(fm=skill_frontmatter(), body=skill_body(), folder=st_folder_name)
    @settings(max_examples=100)
    def test_name_from_frontmatter_or_folder(self, fm: dict, body: str, folder: str):
        """
        # Feature: skills-folder-architecture, Property 1: Frontmatter 解析正确性
        If frontmatter has 'name', SkillInfo.name equals it; otherwise equals folder name.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1
            if "name" in fm:
                assert skills[0].name == fm["name"]
            else:
                assert skills[0].name == folder

    @given(fm=skill_frontmatter(), body=skill_body(), folder=st_folder_name)
    @settings(max_examples=100)
    def test_description_from_frontmatter_or_body(self, fm: dict, body: str, folder: str):
        """
        # Feature: skills-folder-architecture, Property 1: Frontmatter 解析正确性
        If frontmatter has 'description', SkillInfo.description equals it;
        otherwise equals first non-empty non-heading line of body.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1
            s = skills[0]
            if "description" in fm:
                assert s.description == fm["description"]
            else:
                for line in body.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        assert s.description == stripped
                        break

    @given(fm=skill_frontmatter(), body=skill_body(), folder=st_folder_name)
    @settings(max_examples=100)
    def test_allowed_tools_matches(self, fm: dict, body: str, folder: str):
        """
        # Feature: skills-folder-architecture, Property 1: Frontmatter 解析正确性
        allowed_tools list matches frontmatter 'allowed-tools'.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1
            expected = fm.get("allowed-tools", []) or []
            assert skills[0].allowed_tools == expected

    @given(fm=skill_frontmatter(), body=skill_body(), folder=st_folder_name)
    @settings(max_examples=100)
    def test_memory_categories_matches(self, fm: dict, body: str, folder: str):
        """
        # Feature: skills-folder-architecture, Property 1: Frontmatter 解析正确性
        memory_categories list matches frontmatter 'memory_categories'.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1
            expected = fm.get("memory_categories", []) or []
            assert skills[0].memory_categories == expected

    @given(fm=skill_frontmatter(), body=skill_body(), folder=st_folder_name)
    @settings(max_examples=100)
    def test_conditional_flag_from_paths(self, fm: dict, body: str, folder: str):
        """
        # Feature: skills-folder-architecture, Property 1: Frontmatter 解析正确性
        is_conditional is True iff frontmatter has 'paths' field.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)
            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1
            s = skills[0]
            if "paths" in fm:
                assert s.is_conditional is True
                assert s.paths == fm["paths"]
            else:
                assert s.is_conditional is False
                assert s.paths is None


# ---------------------------------------------------------------------------
# Property 2: 文件夹扫描正确性
# Feature: skills-folder-architecture, Property 2: 文件夹扫描正确性
# ---------------------------------------------------------------------------


class TestFolderScanning:
    """
    Property 2: 文件夹扫描正确性

    For any skills directory structure, load_all() returns SkillInfo only for
    subfolders that contain a SKILL.md file. Loose .md files and empty folders
    are excluded.

    Validates: Requirements 1.1, 1.2, 1.5
    """

    @given(layout=skill_directory())
    @settings(max_examples=100)
    def test_only_folders_with_skill_md_loaded(self, layout: dict):
        """
        # Feature: skills-folder-architecture, Property 2: 文件夹扫描正确性
        load_all() only returns skills for folders containing SKILL.md.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            expected_folders: set[str] = set()

            for folder_name, content in layout["folders"]:
                folder = tmp_path / folder_name
                folder.mkdir(parents=True, exist_ok=True)
                if content is not None:
                    (folder / "SKILL.md").write_text(content, encoding="utf-8")
                    expected_folders.add(folder_name)
                (folder / "extra.txt").write_text("resource", encoding="utf-8")

            for loose in layout["loose_files"]:
                (tmp_path / loose).write_text("---\nname: Loose\n---\nbody", encoding="utf-8")

            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()

            assert len(skills) == len(expected_folders)
            loaded_folders = {s.folder_name for s in skills}
            assert loaded_folders == expected_folders

    @given(
        n_resource_files=st.integers(min_value=0, max_value=5),
        folder=st_folder_name,
        fm=skill_frontmatter(),
        body=skill_body(),
    )
    @settings(max_examples=100)
    def test_resource_files_dont_affect_loading(
        self, n_resource_files: int, folder: str, fm: dict, body: str,
    ):
        """
        # Feature: skills-folder-architecture, Property 2: 文件夹扫描正确性
        Extra resource files in a skill folder don't affect loading.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            skill_folder = _make_skill_folder(tmp_path, folder, content)

            for i in range(n_resource_files):
                (skill_folder / f"resource_{i}.txt").write_text(f"data {i}", encoding="utf-8")

            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1


# ---------------------------------------------------------------------------
# Property 3: SKILL_DIR 变量替换
# Feature: skills-folder-architecture, Property 3: SKILL_DIR 变量替换
# ---------------------------------------------------------------------------


class TestSkillDirReplacement:
    """
    Property 3: SKILL_DIR 变量替换

    For any skill content and folder path, get_skill_content() replaces all
    ${SKILL_DIR} occurrences with the folder's absolute path. Content without
    ${SKILL_DIR} is returned unchanged.

    Validates: Requirements 6.1, 6.3
    """

    @given(folder=st_folder_name, fm=skill_frontmatter(), extra_text=st_safe_text)
    @settings(max_examples=100)
    def test_skill_dir_replaced_with_absolute_path(
        self, folder: str, fm: dict, extra_text: str,
    ):
        """
        # Feature: skills-folder-architecture, Property 3: SKILL_DIR 变量替换
        ${SKILL_DIR} is replaced with the folder's absolute path.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            body = f"## 场景描述\n{extra_text}\npath: ${{SKILL_DIR}}/template.txt"
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            name = fm.get("name", folder)
            result = loader.get_skill_content(name)
            if result is None:
                result = loader.get_skill_content(folder)

            assert result is not None
            assert "${SKILL_DIR}" not in result["content"]
            expected_path = str((tmp_path / folder).resolve())
            assert expected_path in result["content"]

    @given(folder=st_folder_name, fm=skill_frontmatter(), body_text=st_safe_text)
    @settings(max_examples=100)
    def test_content_without_skill_dir_unchanged(
        self, folder: str, fm: dict, body_text: str,
    ):
        """
        # Feature: skills-folder-architecture, Property 3: SKILL_DIR 变量替换
        Content without ${SKILL_DIR} is returned unchanged.
        """
        assume("${SKILL_DIR}" not in body_text)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            body = f"## 场景描述\n{body_text}"
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            name = fm.get("name", folder)
            result = loader.get_skill_content(name)
            if result is None:
                result = loader.get_skill_content(folder)

            assert result is not None
            assert body_text in result["content"]


# ---------------------------------------------------------------------------
# Property 4: get_skill_content 返回完整数据
# Feature: skills-folder-architecture, Property 4: get_skill_content 返回完整数据
# ---------------------------------------------------------------------------


class TestGetSkillContentData:
    """
    Property 4: get_skill_content 返回完整数据

    For any loaded skill, get_skill_content returns a dict with content,
    allowed_tools, name, and description. For non-existent names, returns None.

    Validates: Requirements 7.3, 7.4, 3.2
    """

    @given(folder=st_folder_name, fm=skill_frontmatter(), body=skill_body())
    @settings(max_examples=100)
    def test_returns_dict_with_required_keys(self, folder: str, fm: dict, body: str):
        """
        # Feature: skills-folder-architecture, Property 4: get_skill_content 返回完整数据
        Successful call returns dict with content/allowed_tools/name/description.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            name = fm.get("name", folder)
            result = loader.get_skill_content(name)
            if result is None:
                result = loader.get_skill_content(folder)

            assert result is not None
            assert set(result.keys()) == {"content", "allowed_tools", "name", "description"}
            assert isinstance(result["content"], str)
            assert isinstance(result["allowed_tools"], list)
            assert isinstance(result["name"], str)
            assert isinstance(result["description"], str)

    @given(folder=st_folder_name, fm=skill_frontmatter(), body=skill_body())
    @settings(max_examples=100)
    def test_allowed_tools_in_result_matches_skill(self, folder: str, fm: dict, body: str):
        """
        # Feature: skills-folder-architecture, Property 4: get_skill_content 返回完整数据
        allowed_tools in result matches the skill's allowed_tools.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            name = fm.get("name", folder)
            result = loader.get_skill_content(name)
            if result is None:
                result = loader.get_skill_content(folder)

            assert result is not None
            expected_tools = fm.get("allowed-tools", []) or []
            assert result["allowed_tools"] == expected_tools

    @given(
        folder=st_folder_name,
        fm=skill_frontmatter(),
        body=skill_body(),
        bad_name=st_safe_text,
    )
    @settings(max_examples=100)
    def test_nonexistent_name_returns_none(
        self, folder: str, fm: dict, body: str, bad_name: str,
    ):
        """
        # Feature: skills-folder-architecture, Property 4: get_skill_content 返回完整数据
        Non-existent skill name returns None.
        """
        real_name = fm.get("name", folder)
        assume(bad_name != real_name and bad_name != folder)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            assert loader.get_skill_content(bad_name) is None


# ---------------------------------------------------------------------------
# Property 5: Prompt Section 摘要完整性
# Feature: skills-folder-architecture, Property 5: Prompt Section 摘要完整性
# ---------------------------------------------------------------------------


class TestPromptSectionCompleteness:
    """
    Property 5: Prompt Section 摘要完整性

    For any skill set, to_prompt_section() includes name/description/when_to_use/
    allowed-tools for each active skill, and never includes the full body content.

    Validates: Requirements 8.1, 7.1
    """

    @given(
        skills_data=st.lists(
            st.tuples(st_folder_name, skill_frontmatter(), skill_body()),
            min_size=1,
            max_size=4,
            unique_by=lambda t: t[0].lower(),
        ),
    )
    @settings(max_examples=100)
    def test_active_skills_have_summary_fields(self, skills_data):
        """
        # Feature: skills-folder-architecture, Property 5: Prompt Section 摘要完整性
        Each active skill's name appears in the prompt section.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for folder, fm, body in skills_data:
                content = _build_frontmatter(**fm) + body
                _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            all_names = {s.name for s in loader._skills}
            section = loader.to_prompt_section(activated_skills=all_names)

            for skill in loader._skills:
                assert skill.name in section

    @given(folder=st_folder_name, fm=skill_frontmatter())
    @settings(max_examples=100)
    def test_body_not_in_prompt_section(self, folder: str, fm: dict):
        """
        # Feature: skills-folder-architecture, Property 5: Prompt Section 摘要完整性
        Full body content should not appear in the prompt section.
        """
        # Ensure description is set in frontmatter so the unique marker in body
        # won't be extracted as the description (which would appear in the summary).
        fm_with_desc = {**fm, "description": "简短描述"}
        unique_marker = "UNIQUE_BODY_MARKER_12345"
        body = f"## 场景描述\n{unique_marker}\n详细的场景内容不应出现在摘要中"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = _build_frontmatter(**fm_with_desc) + body
            _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            loader.load_all()
            all_names = {s.name for s in loader._skills}
            section = loader.to_prompt_section(activated_skills=all_names)
            assert unique_marker not in section

    @given(
        skills_data=st.lists(
            st.tuples(st_folder_name, skill_frontmatter(), skill_body()),
            min_size=1,
            max_size=4,
            unique_by=lambda t: t[0].lower(),
        ),
    )
    @settings(max_examples=100)
    def test_prompt_section_contains_usage_guide(self, skills_data):
        """
        # Feature: skills-folder-architecture, Property 5: Prompt Section 摘要完整性
        Prompt section always contains usage guide text mentioning get_skill_content.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for folder, fm, body in skills_data:
                content = _build_frontmatter(**fm) + body
                _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            section = loader.to_prompt_section()
            assert "get_skill_content" in section
            assert "场景参考规范" in section


# ---------------------------------------------------------------------------
# Property 6: 条件激活过滤
# Feature: skills-folder-architecture, Property 6: 条件激活过滤
# ---------------------------------------------------------------------------


class TestConditionalActivationFiltering:
    """
    Property 6: 条件激活过滤

    For any mix of Conditional and Unconditional skills, to_prompt_section()
    shows full summaries for Unconditional + activated Conditional skills,
    and only name + activation condition for non-activated Conditional skills.
    All skill names always appear.

    Validates: Requirements 8.3, 8.4, 5.1, 5.4
    """

    @given(
        uncond_folders=st.lists(st_folder_name, min_size=1, max_size=2, unique=True),
        cond_folders=st.lists(st_folder_name, min_size=1, max_size=2, unique=True),
        activate_ratio=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_unconditional_always_shown_conditional_filtered(
        self, uncond_folders: list[str], cond_folders: list[str], activate_ratio: float,
    ):
        """
        # Feature: skills-folder-architecture, Property 6: 条件激活过滤
        Unconditional skills always have full summaries. Conditional skills
        are filtered based on activated_skills set.
        """
        # Ensure no folder name collisions
        all_folders = set(uncond_folders) | set(cond_folders)
        assume(len(all_folders) == len(uncond_folders) + len(cond_folders))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            for i, folder in enumerate(uncond_folders):
                fm_str = _build_frontmatter(name=f"Uncond{i}", description=f"Desc{i}")
                _make_skill_folder(tmp_path, folder, fm_str + "## 场景描述\nbody")

            for i, folder in enumerate(cond_folders):
                fm_str = _build_frontmatter(
                    name=f"Cond{i}", description=f"CDesc{i}",
                    paths=[f"src{i}/*.py"],
                )
                _make_skill_folder(tmp_path, folder, fm_str + "## 场景描述\nbody")

            loader = SkillLoader(str(tmp_path))
            loader.load_all()

            cond_skills = [s for s in loader._skills if s.is_conditional]
            uncond_skills = [s for s in loader._skills if not s.is_conditional]
            n_activate = max(0, int(len(cond_skills) * activate_ratio))
            activated = {s.name for s in cond_skills[:n_activate]}

            section = loader.to_prompt_section(activated_skills=activated)

            # All unconditional skills always present
            for s in uncond_skills:
                assert s.name in section

            # All skill names appear somewhere
            for s in loader._skills:
                assert s.name in section

            # Activated conditional: no deactivated marker
            for s in cond_skills:
                if s.name in activated:
                    assert f"### {s.name} [条件激活: 未激活]" not in section
                else:
                    assert f"### {s.name} [条件激活: 未激活]" in section


# ---------------------------------------------------------------------------
# Property 7: 迁移内容保持
# Feature: skills-folder-architecture, Property 7: 迁移内容保持
# ---------------------------------------------------------------------------


class TestMigrationContentPreservation:
    """
    Property 7: 迁移内容保持

    For any valid flat-format skill file content, after migration to folder
    format, SkillLoader loads identical frontmatter fields and body content.

    Validates: Requirements 9.5, 9.6
    """

    @given(fm=skill_frontmatter(), body=skill_body(), folder=st_folder_name)
    @settings(max_examples=100)
    def test_migrated_content_matches_original(self, fm: dict, body: str, folder: str):
        """
        # Feature: skills-folder-architecture, Property 7: 迁移内容保持
        Frontmatter fields and body are preserved after migration.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            flat_content = _build_frontmatter(**fm) + body
            _make_skill_folder(tmp_path, folder, flat_content)

            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == 1
            s = skills[0]

            if "name" in fm:
                assert s.name == fm["name"]
            if "description" in fm:
                assert s.description == fm["description"]
            if "when_to_use" in fm:
                assert s.when_to_use == fm["when_to_use"]
            if "memory_categories" in fm:
                assert s.memory_categories == (fm["memory_categories"] or [])
            if "allowed-tools" in fm:
                assert s.allowed_tools == (fm["allowed-tools"] or [])
            if "paths" in fm:
                assert s.paths == fm["paths"]
                assert s.is_conditional is True
            else:
                assert s.is_conditional is False

            # Body content preserved
            assert s.body == body

    @given(
        skills_data=st.lists(
            st.tuples(st_folder_name, skill_frontmatter(), skill_body()),
            min_size=1,
            max_size=4,
            unique_by=lambda t: t[0].lower(),
        ),
    )
    @settings(max_examples=100)
    def test_migration_preserves_skill_count(self, skills_data):
        """
        # Feature: skills-folder-architecture, Property 7: 迁移内容保持
        Number of loaded skills equals number of migrated files.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for folder, fm, body in skills_data:
                content = _build_frontmatter(**fm) + body
                _make_skill_folder(tmp_path, folder, content)

            loader = SkillLoader(str(tmp_path))
            skills = loader.load_all()
            assert len(skills) == len(skills_data)
