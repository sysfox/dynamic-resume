# dynamic-resume

通过 GitHub API 自动获取用户 **sysfox** 的开源贡献，分类整理后生成一份美观的 HTML 简历，并通过 GitHub Actions 定期更新、部署至 GitHub Pages。

---

## 🚀 功能特性

- 通过 **GraphQL API**（优先）或 **REST Search API**（备用）拉取所有 PR 与 Issue
- 自动分类为：
  - **📄 文档贡献** — 含文档路径关键词或 `.md`/`.rst` 等扩展名
  - **💻 代码贡献** — 其余所有 PR
  - **💡 有价值的 Issue** — 反应数 ≥ 3 / 评论数 ≥ 5 / 含重要标签，取前 10
- 使用 **Bootstrap 5** 生成响应式 HTML，支持搜索筛选与折叠/展开
- **GitHub Actions** 每周自动运行，结果部署到 `gh-pages`

---

## 📦 依赖

```
requests>=2.31.0
```

安装方式：

```bash
pip install -r requirements.txt
```

---

## 🖥 本地运行

```bash
# 1. 设置 GitHub Token（强烈建议，否则速率限制为 60 次/小时）
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# 2. 运行脚本
python generate_resume.py

# 3. 打开生成的简历
open resume.html         # macOS
xdg-open resume.html     # Linux
start resume.html        # Windows

# 可选：运行后自动在浏览器中打开
AUTO_OPEN=true python generate_resume.py
```

---

## ⚙️ GitHub Actions

工作流文件：`.github/workflows/generate-resume.yml`

| 触发方式 | 说明 |
|----------|------|
| `schedule` | 每周一 UTC 00:00 自动运行 |
| `workflow_dispatch` | 在 Actions 页面手动点击 **Run workflow** |

运行后会将 `resume.html` 推送至 `gh-pages` 分支，可通过以下 URL 访问：

```
https://sysfox.github.io/dynamic-resume/
```

> **注意**：首次使用前请在仓库 Settings → Pages → Source 中选择 `gh-pages` 分支并保存。

---

## 📁 文件结构

```
.
├── generate_resume.py          # 主脚本
├── requirements.txt            # Python 依赖
├── resume.html                 # 生成的简历（由脚本输出）
└── .github/
    └── workflows/
        └── generate-resume.yml # GitHub Actions 工作流
```
