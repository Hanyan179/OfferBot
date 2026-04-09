-- ============================================================
-- Boss 直聘求职 Agent — 数据库 Schema
-- 设计原则：数据是 AI 的养料，每个表都是 AI 可自助查询的维度源
-- AI 通过 Tool 自由组合查询，不需要硬编码分析逻辑
-- ============================================================

-- ============================================================
-- 一、用户侧：人物画像（AI 了解"你是谁、你要什么"）
-- ============================================================

-- 简历/人物画像表
-- AI 匹配、打招呼语生成、反馈分析的核心数据源
-- 支持多版本简历（is_active 标记当前版本）
CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,                       -- 简历来源文件路径
    source_format TEXT DEFAULT 'markdown',  -- markdown / pdf
    -- 基本信息
    name TEXT,                              -- 姓名
    phone TEXT,                             -- 手机
    email TEXT,                             -- 邮箱
    birth_year INTEGER,                     -- 出生年份
    city TEXT,                              -- 现居城市
    -- 教育背景
    education_level TEXT,                   -- 学历等级（大专/本科/硕士/博士）
    education_major TEXT,                   -- 专业
    school TEXT,                            -- 学校
    -- 职业画像
    years_of_experience INTEGER,            -- 工作年限
    current_company TEXT,                   -- 当前公司
    current_role TEXT,                      -- 当前职位
    summary TEXT,                           -- 个人简介
    self_evaluation TEXT,                   -- 自我评价
    -- 结构化技能与经历（JSON，AI 按维度取用）
    tech_stack TEXT,                        -- 技术栈 JSON: {"领域": ["技术1", "技术2"]}
    skills_flat TEXT,                       -- 扁平技能列表 JSON: ["Python", "FastAPI", "Agent"]
    work_experience TEXT,                   -- 工作经历 JSON: [WorkExperience]
    projects TEXT,                          -- 项目经验 JSON: [ProjectExperience]
    highlights TEXT,                        -- 核心亮点 JSON: ["独立完成AI产品全栈", "Agent实战经验"]
    -- 原始数据
    raw_text TEXT,                          -- 原始简历文本
    structured_resume TEXT,                 -- 完整结构化 JSON（StructuredResume 序列化）
    -- 状态
    is_active INTEGER DEFAULT 1,            -- 是否为当前使用的简历
    parsed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户求职意向表
-- 用户想要什么：期望薪资、目标城市、目标岗位、行业偏好等
-- AI 做匹配筛选时从这里取用户的"需求侧"数据
CREATE TABLE IF NOT EXISTS job_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER REFERENCES resumes(id), -- 关联简历（不同简历可有不同意向）
    target_cities TEXT,                     -- 目标城市列表 JSON: ["上海", "北京", "杭州"]
    target_roles TEXT,                      -- 目标岗位类型 JSON: ["AI工程师", "后端开发", "全栈"]
    target_industries TEXT,                 -- 目标行业 JSON: ["互联网", "AI", "金融科技"]
    salary_min INTEGER,                     -- 期望薪资下限（K/月）
    salary_max INTEGER,                     -- 期望薪资上限（K/月）
    experience_match TEXT,                  -- 可接受经验要求 如 "1-5年"
    education_min TEXT,                     -- 最低学历要求 如 "本科"
    company_size_pref TEXT,                 -- 公司规模偏好 JSON: ["100-499人", "500-999人", "1000人以上"]
    work_type TEXT DEFAULT 'full_time',     -- 工作类型: full_time/part_time/remote/hybrid
    deal_breakers TEXT,                     -- 绝对不接受的条件 JSON: ["996", "外包", "无社保"]
    priorities TEXT,                        -- 求职优先级 JSON: ["薪资", "技术成长", "团队氛围"]
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户配置表（通用 KV 配置）
CREATE TABLE IF NOT EXISTS user_preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 黑名单表
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL UNIQUE,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 二、岗位侧：岗位画像（AI 了解"市场要什么"）
-- ============================================================

-- 岗位表
-- 每个岗位是一个完整的"岗位画像"，AI 可按任意维度查询聚合
-- 如：查所有 AI 岗位的 skills 分布、薪资区间、职责共性
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,               -- 岗位 URL（唯一标识）
    platform TEXT NOT NULL DEFAULT 'boss',  -- 招聘平台
    -- 基本信息
    title TEXT,                             -- 岗位名称
    company TEXT,                           -- 公司名称
    salary_min INTEGER,                     -- 薪资下限（K/月）
    salary_max INTEGER,                     -- 薪资上限（K/月）
    salary_months INTEGER,                  -- 薪资月数（如 13薪、14薪、15薪）
    city TEXT,                              -- 工作城市
    district TEXT,                          -- 区/商圈
    work_type TEXT,                         -- 工作类型: full_time/part_time/remote/hybrid
    -- 岗位要求（AI 匹配的核心维度）
    experience TEXT,                        -- 经验要求原文（如 "3-5年"）
    experience_min INTEGER,                 -- 经验要求下限（年）
    experience_max INTEGER,                 -- 经验要求上限（年）
    education TEXT,                         -- 学历要求（大专/本科/硕士/博士）
    skills TEXT,                            -- 技能要求 JSON: ["Python", "PyTorch", "RAG"]
    skills_must TEXT,                       -- 必须技能 JSON: ["Python", "LLM"]
    skills_preferred TEXT,                  -- 优先技能 JSON: ["Kubernetes", "分布式"]
    responsibilities TEXT,                  -- 岗位职责 JSON: ["负责AI Agent开发", "负责RAG系统"]
    -- 公司画像（AI 分析公司维度）
    company_size TEXT,                      -- 公司规模
    company_industry TEXT,                  -- 公司行业
    company_stage TEXT,                     -- 公司阶段（初创/成长/成熟/上市）
    company_description TEXT,               -- 公司简介
    -- 招聘者信息
    recruiter_name TEXT,                    -- 招聘者姓名
    recruiter_title TEXT,                   -- 招聘者职位
    -- 福利与额外信息
    benefits TEXT,                          -- 福利待遇 JSON: ["五险一金", "弹性工作"]
    tags TEXT,                              -- 岗位标签 JSON: ["急招", "新岗位", "团队扩张"]
    -- 原始与结构化数据
    raw_jd TEXT,                            -- 原始 JD 文本
    structured_jd TEXT,                     -- 结构化 JD JSON（StructuredJD 完整序列化）
    -- AI 分析结果（快速访问，详细维度在 match_results 表）
    match_score REAL,                       -- 综合匹配度（0-100）
    match_detail TEXT,                      -- 匹配详情 JSON（冗余，方便快速展示）
    -- 时间戳
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parsed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 三、AI 分析层：匹配结果（AI 产出的结构化分析）
-- ============================================================

-- 匹配分析结果表
-- AI 对"人物画像 × 岗位画像"的多维度评分
-- 反馈闭环时可按维度聚合：高回复率岗位的 skill_score 平均多少？
CREATE TABLE IF NOT EXISTS match_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    resume_id INTEGER NOT NULL REFERENCES resumes(id),
    -- 维度评分（AI 可按任意维度查询聚合）
    overall_score REAL,                     -- 综合匹配度 0-100
    embedding_similarity REAL,              -- 向量相似度 0-100
    skill_score REAL,                       -- 技能匹配度 0-100
    experience_score REAL,                  -- 经验匹配度 0-100
    responsibility_score REAL,              -- 职责匹配度 0-100
    salary_match REAL,                      -- 薪资匹配度 0-100（期望 vs 提供）
    location_match REAL,                    -- 地点匹配度 0-100
    education_match REAL,                   -- 学历匹配度 0-100
    -- 差距分析（AI 生成优化建议的依据）
    missing_skills TEXT,                    -- 缺失技能 JSON: ["Kubernetes", "Spark"]
    matching_skills TEXT,                   -- 匹配技能 JSON: ["Python", "Agent", "RAG"]
    skill_gaps TEXT,                        -- 技能差距详情 JSON: [{"skill":"K8s","level":"required","user_level":"none"}]
    -- LLM 分析
    analysis TEXT,                          -- LLM 生成的详细分析说明
    recommendation TEXT,                    -- AI 推荐理由/不推荐理由
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, resume_id)
);

-- ============================================================
-- 四、业务流程层：投递、面试追踪
-- ============================================================

-- 投递记录表
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    resume_id INTEGER REFERENCES resumes(id), -- 投递时使用的简历版本
    match_result_id INTEGER REFERENCES match_results(id), -- 关联匹配分析
    greeting TEXT,                          -- 使用的打招呼语
    greeting_strategy TEXT,                 -- 打招呼策略说明（AI 为什么这样写）
    status TEXT NOT NULL DEFAULT 'pending', -- pending/sent/failed
    applied_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 五、知识层：RAG 知识库索引
-- ============================================================

-- 知识库文档索引表
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_hash TEXT NOT NULL,
    chunk_count INTEGER,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 六、任务记录
-- ============================================================

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT DEFAULT 'local',
    status TEXT DEFAULT 'running',          -- running / completed / failed / timeout
    progress_text TEXT DEFAULT '',
    data TEXT DEFAULT '{}',                 -- JSON 扩展字段
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);
