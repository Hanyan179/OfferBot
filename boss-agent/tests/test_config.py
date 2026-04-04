"""config 模块单元测试"""

import os
import pytest
from config import Config, load_config, PROJECT_ROOT


class TestConfigDefaults:
    """验证默认配置值"""

    def test_default_config_has_empty_api_key(self):
        cfg = Config()
        assert cfg.dashscope_api_key == ""

    def test_default_db_path_under_project(self):
        cfg = Config()
        assert cfg.db_path.endswith("boss_agent.db")
        assert "db" in cfg.db_path

    def test_default_log_level_is_info(self):
        cfg = Config()
        assert cfg.log_level == "INFO"

    def test_default_match_threshold(self):
        cfg = Config()
        assert cfg.match_threshold == 80.0

    def test_match_weights_sum_to_one(self):
        cfg = Config()
        total = (
            cfg.match_weight_skill
            + cfg.match_weight_experience
            + cfg.match_weight_responsibility
        )
        assert abs(total - 1.0) < 1e-9

    def test_config_is_frozen(self):
        cfg = Config()
        with pytest.raises(AttributeError):
            cfg.log_level = "DEBUG"  # type: ignore[misc]


class TestLoadConfig:
    """验证 load_config 从环境变量读取"""

    def test_reads_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-123")
        cfg = load_config()
        assert cfg.dashscope_api_key == "test-key-123"

    def test_reads_db_path_from_env(self, monkeypatch):
        monkeypatch.setenv("DB_PATH", "/tmp/test.db")
        cfg = load_config()
        assert cfg.db_path == "/tmp/test.db"

    def test_reads_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        cfg = load_config()
        assert cfg.log_level == "DEBUG"

    def test_reads_float_from_env(self, monkeypatch):
        monkeypatch.setenv("MATCH_THRESHOLD", "90.5")
        cfg = load_config()
        assert cfg.match_threshold == 90.5

    def test_reads_int_from_env(self, monkeypatch):
        monkeypatch.setenv("GRADIO_PORT", "8080")
        cfg = load_config()
        assert cfg.gradio_port == 8080

    def test_falls_back_to_defaults_when_env_unset(self):
        # 确保关键环境变量未设置
        for key in ("DASHSCOPE_API_KEY", "DB_PATH", "LOG_LEVEL"):
            os.environ.pop(key, None)
        cfg = load_config()
        assert cfg.log_level == "INFO"
        assert cfg.dashscope_api_key == ""


class TestProjectRoot:
    """验证 PROJECT_ROOT 指向正确位置"""

    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()

    def test_project_root_contains_config(self):
        assert (PROJECT_ROOT / "config.py").exists()
