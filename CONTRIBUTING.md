# 贡献指南

感谢你对 OfferBot 的关注！

## 如何贡献

1. Fork 本仓库
2. 创建你的分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m "feat: 你的改动"`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

## 开发环境

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r boss-agent/requirements.txt
```

## 开发新 Tool

参见 [Tool 开发指南](docs/tool-development.md)。

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

- `feat:` 新功能
- `fix:` 修复
- `docs:` 文档
- `refactor:` 重构
- `test:` 测试

## 问题反馈

直接提 [Issue](https://github.com/Hanyan179/OfferBot/issues)，描述清楚问题和复现步骤即可。
