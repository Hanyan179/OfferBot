"""Database 模块单元测试"""

import pytest
import pytest_asyncio

from db.database import Database

EXPECTED_TABLES = [
    "jobs",
    "applications",
    "user_preferences",
    "blacklist",
    "knowledge_docs",
    "resumes",
    "job_preferences",
    "match_results",
    "tasks",
]


@pytest_asyncio.fixture
async def db(tmp_path):
    """提供一个已初始化 schema 的内存数据库。"""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


class TestSchemaInit:
    """验证 schema 初始化创建所有 7 张表。"""

    @pytest.mark.asyncio
    async def test_all_tables_created(self, db: Database):
        rows = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = sorted(r["name"] for r in rows)
        assert table_names == sorted(EXPECTED_TABLES)

    @pytest.mark.asyncio
    async def test_table_count(self, db: Database):
        rows = await db.execute(
            "SELECT count(*) AS cnt FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        assert rows[0]["cnt"] == 9


class TestExecute:
    """验证 execute() 返回 list[dict]。"""

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self, db: Database):
        result = await db.execute("SELECT 1 AS a, 'hello' AS b")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {"a": 1, "b": "hello"}

    @pytest.mark.asyncio
    async def test_empty_result(self, db: Database):
        result = await db.execute("SELECT * FROM jobs")
        assert result == []


class TestExecuteWrite:
    """验证 execute_write() 返回 lastrowid。"""

    @pytest.mark.asyncio
    async def test_returns_lastrowid(self, db: Database):
        rowid = await db.execute_write(
            "INSERT INTO jobs (url) VALUES (?)", ("https://example.com/job/1",)
        )
        assert rowid == 1

    @pytest.mark.asyncio
    async def test_sequential_inserts(self, db: Database):
        id1 = await db.execute_write(
            "INSERT INTO jobs (url) VALUES (?)", ("https://example.com/job/1",)
        )
        id2 = await db.execute_write(
            "INSERT INTO jobs (url) VALUES (?)", ("https://example.com/job/2",)
        )
        assert id2 == id1 + 1


class TestPragmas:
    """验证 WAL 模式和外键约束已启用。"""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, db: Database):
        rows = await db.execute("PRAGMA journal_mode")
        assert rows[0]["journal_mode"] == "wal"

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, db: Database):
        rows = await db.execute("PRAGMA foreign_keys")
        assert rows[0]["foreign_keys"] == 1


class TestKnowledgeDocs:
    """验证 knowledge_docs 表基本 CRUD。"""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db: Database):
        rowid = await db.execute_write(
            "INSERT INTO knowledge_docs (file_path, file_hash, chunk_count) VALUES (?, ?, ?)",
            ("docs/rag.md", "abc123", 10),
        )
        assert rowid >= 1
        rows = await db.execute("SELECT * FROM knowledge_docs WHERE id = ?", (rowid,))
        assert len(rows) == 1
        doc = rows[0]
        assert doc["file_path"] == "docs/rag.md"
        assert doc["file_hash"] == "abc123"
        assert doc["chunk_count"] == 10
        assert doc["indexed_at"] is not None

    @pytest.mark.asyncio
    async def test_file_path_unique(self, db: Database):
        await db.execute_write(
            "INSERT INTO knowledge_docs (file_path, file_hash) VALUES (?, ?)",
            ("docs/a.md", "hash1"),
        )
        # 重复 file_path 应报错
        with pytest.raises(Exception):
            await db.execute_write(
                "INSERT INTO knowledge_docs (file_path, file_hash) VALUES (?, ?)",
                ("docs/a.md", "hash2"),
            )

    @pytest.mark.asyncio
    async def test_update_hash_on_change(self, db: Database):
        rowid = await db.execute_write(
            "INSERT INTO knowledge_docs (file_path, file_hash, chunk_count) VALUES (?, ?, ?)",
            ("docs/b.md", "old_hash", 5),
        )
        await db.execute_write(
            "UPDATE knowledge_docs SET file_hash = ?, chunk_count = ?, indexed_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("new_hash", 8, rowid),
        )
        rows = await db.execute("SELECT * FROM knowledge_docs WHERE id = ?", (rowid,))
        assert rows[0]["file_hash"] == "new_hash"
        assert rows[0]["chunk_count"] == 8


class TestResumes:
    """验证 resumes 表（人物画像）基本 CRUD。"""

    @pytest.mark.asyncio
    async def test_insert_and_query_all_fields(self, db: Database):
        import json
        tech_stack = json.dumps({"后端": ["Python", "FastAPI"], "AI": ["LLM", "RAG"]})
        skills_flat = json.dumps(["Python", "FastAPI", "LLM", "RAG", "Agent"])
        work_exp = json.dumps([{"company": "测试公司", "role": "工程师", "duration": "2年"}])
        projects = json.dumps([{"name": "AI Agent", "description": "求职Agent"}])
        highlights = json.dumps(["独立完成AI产品全栈", "Agent实战经验"])

        rowid = await db.execute_write(
            "INSERT INTO resumes "
            "(source_path, source_format, name, phone, email, birth_year, city, "
            "education_level, education_major, school, "
            "years_of_experience, current_company, current_role, summary, self_evaluation, "
            "tech_stack, skills_flat, work_experience, projects, highlights, raw_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("resume.md", "markdown", "张三", "13800138000", "test@example.com",
             2000, "上海",
             "本科", "计算机科学与技术", "测试大学",
             4, "测试科技公司", "AI工程师", "4年研发经验", "全栈能力强",
             tech_stack, skills_flat, work_exp, projects, highlights, "# 简历原文"),
        )
        rows = await db.execute("SELECT * FROM resumes WHERE id = ?", (rowid,))
        assert len(rows) == 1
        r = rows[0]
        assert r["name"] == "张三"
        assert r["birth_year"] == 2000
        assert r["city"] == "上海"
        assert r["education_level"] == "本科"
        assert r["education_major"] == "计算机科学与技术"
        assert r["school"] == "测试大学"
        assert r["years_of_experience"] == 4
        assert r["current_company"] == "测试科技公司"
        assert r["current_role"] == "AI工程师"
        assert r["summary"] == "4年研发经验"
        assert r["self_evaluation"] == "全栈能力强"
        assert json.loads(r["tech_stack"])["后端"] == ["Python", "FastAPI"]
        assert json.loads(r["skills_flat"]) == ["Python", "FastAPI", "LLM", "RAG", "Agent"]
        assert json.loads(r["work_experience"])[0]["company"] == "测试公司"
        assert json.loads(r["projects"])[0]["name"] == "AI Agent"
        assert json.loads(r["highlights"]) == ["独立完成AI产品全栈", "Agent实战经验"]
        assert r["is_active"] == 1
        assert r["created_at"] is not None

    @pytest.mark.asyncio
    async def test_only_one_active_resume(self, db: Database):
        """验证可以通过 is_active 标记管理多版本简历"""
        r1 = await db.execute_write(
            "INSERT INTO resumes (name, is_active) VALUES (?, ?)", ("v1", 1)
        )
        r2 = await db.execute_write(
            "INSERT INTO resumes (name, is_active) VALUES (?, ?)", ("v2", 0)
        )
        active = await db.execute("SELECT * FROM resumes WHERE is_active = 1")
        assert len(active) == 1
        assert active[0]["name"] == "v1"

    @pytest.mark.asyncio
    async def test_structured_resume_json(self, db: Database):
        """验证 structured_resume 字段可存储完整序列化 JSON"""
        import json
        full_struct = {
            "name": "张三", "phone": "138", "email": "a@b.com",
            "city": "上海", "education": "本科", "years_of_experience": 4,
            "tech_stack": {"后端": ["Python"]},
            "work_experience": [], "projects": [], "summary": "简介"
        }
        rowid = await db.execute_write(
            "INSERT INTO resumes (name, structured_resume) VALUES (?, ?)",
            ("张三", json.dumps(full_struct, ensure_ascii=False)),
        )
        rows = await db.execute("SELECT structured_resume FROM resumes WHERE id = ?", (rowid,))
        parsed = json.loads(rows[0]["structured_resume"])
        assert parsed["tech_stack"]["后端"] == ["Python"]
        assert parsed["years_of_experience"] == 4


class TestMatchResults:
    """验证 match_results 表（AI 维度评分持久化）。"""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db: Database):
        import json
        job_id = await db.execute_write(
            "INSERT INTO jobs (url, title) VALUES (?, ?)",
            ("https://example.com/job/match", "AI 工程师"),
        )
        resume_id = await db.execute_write(
            "INSERT INTO resumes (name) VALUES (?)", ("张三",)
        )
        missing = json.dumps(["Kubernetes", "Spark"])
        matching = json.dumps(["Python", "Agent", "RAG"])
        gaps = json.dumps([{"skill": "K8s", "level": "required", "user_level": "none"}])
        rowid = await db.execute_write(
            "INSERT INTO match_results "
            "(job_id, resume_id, overall_score, embedding_similarity, "
            "skill_score, experience_score, responsibility_score, "
            "salary_match, location_match, education_match, "
            "missing_skills, matching_skills, skill_gaps, analysis, recommendation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, resume_id, 85.5, 78.0, 90.0, 80.0, 85.0,
             95.0, 100.0, 100.0,
             missing, matching, gaps, "匹配度较高", "推荐投递"),
        )
        rows = await db.execute("SELECT * FROM match_results WHERE id = ?", (rowid,))
        assert len(rows) == 1
        m = rows[0]
        assert m["job_id"] == job_id
        assert m["resume_id"] == resume_id
        assert m["overall_score"] == 85.5
        assert m["skill_score"] == 90.0
        assert m["experience_score"] == 80.0
        assert m["responsibility_score"] == 85.0
        assert m["salary_match"] == 95.0
        assert m["location_match"] == 100.0
        assert m["education_match"] == 100.0
        assert json.loads(m["missing_skills"]) == ["Kubernetes", "Spark"]
        assert json.loads(m["matching_skills"]) == ["Python", "Agent", "RAG"]
        assert json.loads(m["skill_gaps"])[0]["skill"] == "K8s"
        assert m["recommendation"] == "推荐投递"

    @pytest.mark.asyncio
    async def test_unique_job_resume_pair(self, db: Database):
        """同一简历对同一岗位只能有一条匹配记录"""
        job_id = await db.execute_write(
            "INSERT INTO jobs (url) VALUES (?)", ("https://example.com/dup",)
        )
        resume_id = await db.execute_write(
            "INSERT INTO resumes (name) VALUES (?)", ("李四",)
        )
        await db.execute_write(
            "INSERT INTO match_results (job_id, resume_id, overall_score) VALUES (?, ?, ?)",
            (job_id, resume_id, 80.0),
        )
        with pytest.raises(Exception):
            await db.execute_write(
                "INSERT INTO match_results (job_id, resume_id, overall_score) VALUES (?, ?, ?)",
                (job_id, resume_id, 90.0),
            )

    @pytest.mark.asyncio
    async def test_query_by_dimension(self, db: Database):
        """验证可以按维度查询，支持反馈分析"""
        job1 = await db.execute_write("INSERT INTO jobs (url) VALUES (?)", ("https://a.com/1",))
        job2 = await db.execute_write("INSERT INTO jobs (url) VALUES (?)", ("https://a.com/2",))
        rid = await db.execute_write("INSERT INTO resumes (name) VALUES (?)", ("王五",))

        await db.execute_write(
            "INSERT INTO match_results (job_id, resume_id, overall_score, skill_score, experience_score) "
            "VALUES (?, ?, ?, ?, ?)",
            (job1, rid, 90.0, 95.0, 85.0),
        )
        await db.execute_write(
            "INSERT INTO match_results (job_id, resume_id, overall_score, skill_score, experience_score) "
            "VALUES (?, ?, ?, ?, ?)",
            (job2, rid, 60.0, 50.0, 70.0),
        )

        # AI 反馈分析：查找技能匹配度 > 80 的岗位
        high_skill = await db.execute(
            "SELECT * FROM match_results WHERE skill_score > ? ORDER BY skill_score DESC",
            (80.0,),
        )
        assert len(high_skill) == 1
        assert high_skill[0]["job_id"] == job1

        # 聚合：平均各维度分数
        avg = await db.execute(
            "SELECT AVG(skill_score) AS avg_skill, AVG(experience_score) AS avg_exp "
            "FROM match_results"
        )
        assert avg[0]["avg_skill"] == pytest.approx(72.5)
        assert avg[0]["avg_exp"] == pytest.approx(77.5)


class TestJobPreferences:
    """验证 job_preferences 表（用户求职意向）。"""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db: Database):
        import json
        resume_id = await db.execute_write(
            "INSERT INTO resumes (name) VALUES (?)", ("张三",)
        )
        rowid = await db.execute_write(
            "INSERT INTO job_preferences "
            "(resume_id, target_cities, target_roles, target_industries, "
            "salary_min, salary_max, experience_match, education_min, "
            "company_size_pref, work_type, deal_breakers, priorities) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (resume_id,
             json.dumps(["上海", "北京", "杭州"]),
             json.dumps(["AI工程师", "后端开发"]),
             json.dumps(["互联网", "AI"]),
             20, 40, "1-5年", "本科",
             json.dumps(["100-499人", "500-999人"]),
             "full_time",
             json.dumps(["996", "外包"]),
             json.dumps(["薪资", "技术成长"])),
        )
        rows = await db.execute("SELECT * FROM job_preferences WHERE id = ?", (rowid,))
        assert len(rows) == 1
        p = rows[0]
        assert p["resume_id"] == resume_id
        assert json.loads(p["target_cities"]) == ["上海", "北京", "杭州"]
        assert json.loads(p["target_roles"]) == ["AI工程师", "后端开发"]
        assert p["salary_min"] == 20
        assert p["salary_max"] == 40
        assert p["work_type"] == "full_time"
        assert json.loads(p["deal_breakers"]) == ["996", "外包"]
        assert json.loads(p["priorities"]) == ["薪资", "技术成长"]
        assert p["is_active"] == 1

    @pytest.mark.asyncio
    async def test_ai_can_cross_query_user_vs_job(self, db: Database):
        """验证 AI 可以交叉查询用户意向 vs 岗位数据"""
        import json
        # 用户意向：上海，20-40K
        rid = await db.execute_write("INSERT INTO resumes (name, city) VALUES (?, ?)", ("张三", "上海"))
        await db.execute_write(
            "INSERT INTO job_preferences (resume_id, target_cities, salary_min, salary_max) "
            "VALUES (?, ?, ?, ?)",
            (rid, json.dumps(["上海"]), 20, 40),
        )
        # 岗位：上海 25-45K（匹配）、北京 30-50K（城市不匹配）
        await db.execute_write(
            "INSERT INTO jobs (url, title, city, salary_min, salary_max) VALUES (?, ?, ?, ?, ?)",
            ("https://a.com/1", "AI工程师", "上海", 25, 45),
        )
        await db.execute_write(
            "INSERT INTO jobs (url, title, city, salary_min, salary_max) VALUES (?, ?, ?, ?, ?)",
            ("https://a.com/2", "AI工程师", "北京", 30, 50),
        )

        # AI 查询：用户意向城市内、薪资范围有交集的岗位
        prefs = await db.execute(
            "SELECT target_cities, salary_min, salary_max FROM job_preferences WHERE resume_id = ? AND is_active = 1",
            (rid,),
        )
        cities = json.loads(prefs[0]["target_cities"])
        user_min = prefs[0]["salary_min"]
        user_max = prefs[0]["salary_max"]

        # 城市匹配 + 薪资有交集
        placeholders = ",".join("?" for _ in cities)
        matched_jobs = await db.execute(
            f"SELECT * FROM jobs WHERE city IN ({placeholders}) "
            "AND salary_min <= ? AND salary_max >= ?",
            (*cities, user_max, user_min),
        )
        assert len(matched_jobs) == 1
        assert matched_jobs[0]["city"] == "上海"


class TestJobsNewFields:
    """验证 jobs 表新增的 AI 维度字段。"""

    @pytest.mark.asyncio
    async def test_skills_split_fields(self, db: Database):
        """验证 skills / skills_must / skills_preferred 三级技能字段"""
        import json
        job_id = await db.execute_write(
            "INSERT INTO jobs (url, title, skills, skills_must, skills_preferred) "
            "VALUES (?, ?, ?, ?, ?)",
            ("https://a.com/skills",
             "AI工程师",
             json.dumps(["Python", "PyTorch", "RAG", "Agent", "K8s"]),
             json.dumps(["Python", "RAG"]),
             json.dumps(["K8s", "分布式"])),
        )
        rows = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        j = rows[0]
        all_skills = json.loads(j["skills"])
        must = json.loads(j["skills_must"])
        preferred = json.loads(j["skills_preferred"])
        assert "Python" in all_skills
        assert "Python" in must
        assert "K8s" in preferred
        # must 是 skills 的子集
        assert all(s in all_skills for s in must)

    @pytest.mark.asyncio
    async def test_salary_months_and_experience_range(self, db: Database):
        """验证薪资月数和经验范围数值字段"""
        job_id = await db.execute_write(
            "INSERT INTO jobs (url, salary_min, salary_max, salary_months, "
            "experience, experience_min, experience_max) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://a.com/salary", 20, 40, 15, "3-5年", 3, 5),
        )
        rows = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        j = rows[0]
        assert j["salary_months"] == 15
        assert j["experience_min"] == 3
        assert j["experience_max"] == 5
        # AI 可以计算年薪范围
        annual_min = j["salary_min"] * j["salary_months"]
        annual_max = j["salary_max"] * j["salary_months"]
        assert annual_min == 300
        assert annual_max == 600

    @pytest.mark.asyncio
    async def test_company_profile_fields(self, db: Database):
        """验证公司画像字段"""
        job_id = await db.execute_write(
            "INSERT INTO jobs (url, company, company_size, company_industry, "
            "company_stage, company_description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("https://a.com/company", "测试科技", "100-499人", "AI",
             "成长期", "专注AI Agent开发"),
        )
        rows = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        j = rows[0]
        assert j["company_stage"] == "成长期"
        assert j["company_description"] == "专注AI Agent开发"
