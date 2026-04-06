"""知识图谱数据 API — 用户图谱 + 岗位图谱 + 匹配图谱"""

from __future__ import annotations

import json
import os
from pathlib import Path

import networkx as nx


def build_user_graph(db_conn) -> dict:
    """从数据库构建用户个人知识图谱。"""
    db_conn.row_factory = _dict_factory
    resume = db_conn.execute("SELECT * FROM resumes WHERE is_active = 1 LIMIT 1").fetchone()
    prefs = db_conn.execute("SELECT * FROM job_preferences WHERE is_active = 1 LIMIT 1").fetchone()
    if not resume:
        return {"nodes": [], "edges": []}

    skills = _parse_json(resume.get("skills_flat"), [])
    work_exp = _parse_json(resume.get("work_experience"), [])
    projects = _parse_json(resume.get("projects"), [])
    target_roles = _parse_json(prefs.get("target_roles"), []) if prefs else []
    target_cities = _parse_json(prefs.get("target_cities"), []) if prefs else []
    priorities = _parse_json(prefs.get("priorities"), []) if prefs else []
    salary_min = prefs["salary_min"] if prefs else 0
    salary_max = prefs["salary_max"] if prefs else 0

    nodes, edges = [], []

    # 用户中心
    nodes.append({"id": "user", "label": resume["name"], "type": "用户", "size": 40})

    # 技能
    for s in skills:
        nid = f"skill_{s}"
        nodes.append({"id": nid, "label": s, "type": "技能", "size": 15})
        edges.append({"source": "user", "target": nid, "label": "掌握"})

    # 目标角色
    for r in target_roles:
        nid = f"role_{r}"
        nodes.append({"id": nid, "label": r, "type": "目标角色", "size": 18})
        edges.append({"source": "user", "target": nid, "label": "目标"})

    # 城市
    for c in target_cities:
        nid = f"city_{c}"
        nodes.append({"id": nid, "label": c, "type": "城市", "size": 18})
        edges.append({"source": "user", "target": nid, "label": "目标城市"})

    # 薪资
    if salary_min or salary_max:
        sal = f"{salary_min}-{salary_max}K"
        nodes.append({"id": f"salary_{sal}", "label": sal, "type": "薪资", "size": 15})
        edges.append({"source": "user", "target": f"salary_{sal}", "label": "期望薪资"})

    # 工作经历
    for w in work_exp:
        nid = f"work_{w['company']}"
        nodes.append({"id": nid, "label": w["company"][:20], "type": "工作经历", "size": 15})
        edges.append({"source": "user", "target": nid, "label": w.get("role", "任职")[:15]})

    # 项目
    for p in projects:
        nid = f"proj_{p['name']}"
        nodes.append({"id": nid, "label": p["name"], "type": "项目", "size": 18})
        edges.append({"source": "user", "target": nid, "label": "主导"})

    # 求职偏好
    for pr in priorities:
        nid = f"priority_{pr}"
        nodes.append({"id": nid, "label": pr, "type": "求职偏好", "size": 12})
        edges.append({"source": "user", "target": nid, "label": "优先"})

    return {"nodes": nodes, "edges": edges}


def build_jobs_graph(lightrag_dir: str) -> dict:
    """从 LightRAG 的 graphml 文件读取岗位图谱。"""
    graphml = os.path.join(lightrag_dir, "graph_chunk_entity_relation.graphml")
    if not os.path.exists(graphml):
        return {"nodes": [], "edges": []}

    G = nx.read_graphml(graphml)
    nodes = []
    for n, d in G.nodes(data=True):
        nodes.append({
            "id": n,
            "label": n[:30],
            "type": d.get("entity_type", "other"),
            "description": d.get("description", "")[:100],
        })
    edges = []
    for u, v, d in G.edges(data=True):
        edges.append({
            "source": u,
            "target": v,
            "label": d.get("description", "")[:50],
        })
    return {"nodes": nodes, "edges": edges}


def build_match_graph(db_conn, lightrag_dir: str, job_id: int) -> dict:
    """构建用户与指定岗位的匹配图谱。"""
    user_graph = build_user_graph(db_conn)
    user_skills = {n["label"] for n in user_graph["nodes"] if n["type"] == "技能"}

    # 从岗位图谱找该岗位关联的技能
    graphml = os.path.join(lightrag_dir, "graph_chunk_entity_relation.graphml")
    if not os.path.exists(graphml):
        return {"nodes": [], "edges": [], "match_summary": {}}

    G = nx.read_graphml(graphml)

    # 找岗位节点（通过 ID 或名称匹配）
    job_node = None
    db_conn.row_factory = _dict_factory
    job_row = db_conn.execute("SELECT title FROM jobs WHERE id = ?", (job_id,)).fetchone()
    job_title = job_row["title"] if job_row else ""

    for n, d in G.nodes(data=True):
        if d.get("entity_type") == "岗位" and (str(job_id) in n or job_title in n):
            job_node = n
            break

    if not job_node:
        return {"nodes": [], "edges": [], "match_summary": {"error": f"未找到岗位 {job_id}"}}

    # 找岗位关联的技能
    job_skills = set()
    for _, target, d in G.edges(job_node, data=True):
        if G.nodes[target].get("entity_type") == "技能":
            job_skills.add(target)

    matched = user_skills & job_skills
    missing = job_skills - user_skills

    return {
        "nodes": user_graph["nodes"],
        "edges": user_graph["edges"],
        "job_node": job_node,
        "match_summary": {
            "matched_skills": sorted(matched),
            "missing_skills": sorted(missing),
            "match_rate": round(len(matched) / max(len(job_skills), 1), 2),
            "job_title": job_title,
        },
    }


def _parse_json(val, default):
    if not val:
        return default
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
