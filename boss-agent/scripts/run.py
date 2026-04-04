#!/usr/bin/env python3
"""
Boss Agent 主入口脚本

启动 Chainlit Web 应用。
用法: cd boss-agent/web && chainlit run app.py
或:   python -m scripts.run
"""

import logging
import subprocess
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import load_config


def main() -> None:
    cfg = load_config()

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("boss-agent")

    if not cfg.dashscope_api_key:
        logger.warning(
            "DASHSCOPE_API_KEY 未设置，AI 功能将不可用。"
        )

    logger.info("Boss Agent 启动中 ...")
    logger.info("地址: http://%s:%s", cfg.gradio_host, cfg.gradio_port)

    web_dir = Path(__file__).resolve().parent.parent / "web"
    subprocess.run(
        [
            sys.executable, "-m", "chainlit", "run", "app.py",
            "--host", cfg.gradio_host,
            "--port", str(cfg.gradio_port),
        ],
        cwd=str(web_dir),
    )


if __name__ == "__main__":
    main()
