#!/usr/bin/env python3
"""
dynamic-resume: 通过 GitHub API 获取用户 sysfox 的开源贡献并生成美观 HTML 简历。

要求 Python >= 3.9（使用了内置泛型类型注解）。

依赖安装：
    pip install requests

用法：
    export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
    python generate_resume.py

生成文件：
    resume.html
"""

import os
import sys

# 检查 Python 版本
if sys.version_info < (3, 9):
    print("❌ 需要 Python 3.9 或更高版本，当前版本：" + sys.version)
    sys.exit(1)

import json
import time
import webbrowser
import datetime
import re
import html as html_module
from typing import Optional

try:
    import requests
except ImportError:
    print("❌ 缺少依赖库 requests，请运行：pip install requests")
    sys.exit(1)

# ─────────────────────── 配置 ───────────────────────
GITHUB_USER = "sysfox"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL = "https://api.github.com/graphql"
REST_BASE = "https://api.github.com"
OUTPUT_FILE = "resume.html"
AUTO_OPEN_BROWSER = os.environ.get("AUTO_OPEN", "false").lower() == "true"

# 文档相关关键词（路径 & 标题均适用）
DOC_PATH_PATTERNS = re.compile(
    r"(^|/)(docs?|readme|changelog|contributing|license|\.github)(/|$)|"
    r"\.(md|rst|txt|adoc|asciidoc|markdown)$",
    re.IGNORECASE,
)
DOC_TITLE_PATTERNS = re.compile(
    r"\b(doc|docs|document|documentation|typo|readme|changelog|contributing)\b",
    re.IGNORECASE,
)

# 有价值 Issue 的标签
VALUABLE_LABELS = {"bug", "enhancement", "good first issue", "help wanted", "feature"}

# 每次请求后的礼貌延迟（秒），避免触发速率限制
REQUEST_DELAY = 0.3


# ─────────────────────── HTTP 工具 ───────────────────────
def make_session() -> requests.Session:
    """创建带认证头的 requests Session。"""
    session = requests.Session()
    if not GITHUB_TOKEN:
        print("⚠️  未设置 GITHUB_TOKEN 环境变量，将使用未认证请求（速率限制更严格）。")
    else:
        session.headers.update(
            {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
    return session


def safe_get(session: requests.Session, url: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    """发起 GET 请求，自动重试、处理速率限制。"""
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset_at - int(time.time()), 1)
                print(f"  ⏳ 触发速率限制，等待 {wait}s 后重试…")
                time.sleep(wait)
                continue
            if resp.status_code == 422:
                # 搜索结果为空时 GitHub 有时返回 422
                return {"items": [], "total_count": 0}
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            print(f"  ⚠️  请求失败（尝试 {attempt + 1}/{retries}）：{exc}")
            time.sleep(2 ** attempt)
    return {}


def graphql_query(session: requests.Session, query: str, variables: dict) -> dict:
    """执行 GraphQL 查询，返回 data 字段内容。"""
    try:
        resp = session.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        if "errors" in result:
            print(f"  ⚠️  GraphQL 错误：{result['errors']}")
        return result.get("data", {})
    except requests.RequestException as exc:
        print(f"  ⚠️  GraphQL 请求失败：{exc}")
        return {}


# ─────────────────────── 数据获取 ───────────────────────

def fetch_user_profile(session: requests.Session) -> dict:
    """获取用户基础信息（头像、简介等）。"""
    print(f"📡 获取用户 {GITHUB_USER} 的基础信息…")
    data = safe_get(session, f"{REST_BASE}/users/{GITHUB_USER}")
    return {
        "login": data.get("login", GITHUB_USER),
        "name": data.get("name") or GITHUB_USER,
        "bio": data.get("bio") or "Open Source Contributor",
        "avatar_url": data.get("avatar_url", ""),
        "html_url": data.get("html_url", f"https://github.com/{GITHUB_USER}"),
        "public_repos": data.get("public_repos", 0),
        "followers": data.get("followers", 0),
    }


def fetch_pull_requests_graphql(session: requests.Session) -> list:
    """
    通过 GraphQL 获取用户作为作者的所有 Pull Request（包含文件改动路径）。
    每次最多拉取 100 条，自动翻页直到全部获取。
    """
    print("📡 [GraphQL] 获取 Pull Request 列表…")
    query = """
    query($login: String!, $after: String) {
      user(login: $login) {
        pullRequests(
          first: 100
          after: $after
          orderBy: {field: CREATED_AT, direction: DESC}
        ) {
          pageInfo { hasNextPage endCursor }
          nodes {
            title
            url
            createdAt
            mergedAt
            state
            repository { nameWithOwner }
            labels(first: 10) { nodes { name } }
            reactions { totalCount }
            comments { totalCount }
            files(first: 50) { nodes { path } }
          }
        }
      }
    }
    """
    prs = []
    cursor = None
    page = 1
    while True:
        print(f"  第 {page} 页 PR…", end=" ", flush=True)
        data = graphql_query(session, query, {"login": GITHUB_USER, "after": cursor})
        user_data = data.get("user") or {}
        pr_data = user_data.get("pullRequests") or {}
        nodes = pr_data.get("nodes") or []
        print(f"获得 {len(nodes)} 条")
        for node in nodes:
            prs.append({
                "type": "pr",
                "repo": node.get("repository", {}).get("nameWithOwner", ""),
                "title": node.get("title", ""),
                "url": node.get("url", ""),
                "created_at": node.get("createdAt", ""),
                "merged_at": node.get("mergedAt"),
                "state": node.get("state", "").lower(),
                "labels": [lbl["name"] for lbl in (node.get("labels") or {}).get("nodes", [])],
                "reactions": (node.get("reactions") or {}).get("totalCount", 0),
                "comments": (node.get("comments") or {}).get("totalCount", 0),
                "files": [f["path"] for f in (node.get("files") or {}).get("nodes", [])],
            })
        page_info = pr_data.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        page += 1
        time.sleep(REQUEST_DELAY)
    print(f"  ✅ 共获取 {len(prs)} 条 PR")
    return prs


def fetch_pull_requests_rest(session: requests.Session) -> list:
    """
    备用：通过 REST Search API 搜索用户创建的 PR。
    Search API 最多返回 1000 条结果（每页 100 条，共 10 页）。
    """
    print("📡 [REST] 获取 Pull Request 列表…")
    prs = []
    page = 1
    while True:
        print(f"  第 {page} 页…", end=" ", flush=True)
        data = safe_get(
            session,
            f"{REST_BASE}/search/issues",
            params={
                "q": f"author:{GITHUB_USER} is:pr",
                "sort": "created",
                "order": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        items = data.get("items") or []
        print(f"获得 {len(items)} 条")
        if not items:
            break
        for item in items:
            prs.append({
                "type": "pr",
                "repo": _extract_repo_from_url(item.get("html_url", "")),
                "title": item.get("title", ""),
                "url": item.get("html_url", ""),
                "created_at": item.get("created_at", ""),
                "merged_at": item.get("pull_request", {}).get("merged_at"),
                "state": "merged" if item.get("pull_request", {}).get("merged_at") else item.get("state", ""),
                "labels": [lbl["name"] for lbl in item.get("labels", [])],
                "reactions": item.get("reactions", {}).get("total_count", 0),
                "comments": item.get("comments", 0),
                "files": [],  # REST Search API 不返回文件，需额外请求（可选）
            })
        if len(items) < 100:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    print(f"  ✅ 共获取 {len(prs)} 条 PR（REST，文件列表为空）")
    return prs


def fetch_issues(session: requests.Session) -> list:
    """
    通过 REST Search API 获取用户创建的 Issue（已排除 PR）。
    """
    print("📡 获取 Issue 列表…")
    issues = []
    page = 1
    while True:
        print(f"  第 {page} 页 Issue…", end=" ", flush=True)
        data = safe_get(
            session,
            f"{REST_BASE}/search/issues",
            params={
                "q": f"author:{GITHUB_USER} is:issue",
                "sort": "reactions",
                "order": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        items = data.get("items") or []
        print(f"获得 {len(items)} 条")
        if not items:
            break
        for item in items:
            label_names = [lbl["name"].lower() for lbl in item.get("labels", [])]
            issues.append({
                "type": "issue",
                "repo": _extract_repo_from_url(item.get("html_url", "")),
                "title": item.get("title", ""),
                "url": item.get("html_url", ""),
                "created_at": item.get("created_at", ""),
                "state": item.get("state", ""),
                "labels": [lbl["name"] for lbl in item.get("labels", [])],
                "reactions": item.get("reactions", {}).get("total_count", 0),
                "comments": item.get("comments", 0),
                "label_names_lower": label_names,
            })
        if len(items) < 100:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    print(f"  ✅ 共获取 {len(issues)} 条 Issue")
    return issues


def _extract_repo_from_url(url: str) -> str:
    """从 GitHub URL 中提取 owner/repo 格式的仓库名。"""
    # 例：https://github.com/owner/repo/issues/1 → owner/repo
    m = re.search(r"github\.com/([^/]+/[^/]+)", url)
    return m.group(1) if m else url


# ─────────────────────── 分类逻辑 ───────────────────────

def is_doc_contribution(item: dict) -> bool:
    """判断 PR/Commit 是否属于文档贡献。"""
    # 1. 标题关键词匹配
    if DOC_TITLE_PATTERNS.search(item.get("title", "")):
        return True
    # 2. 改动文件路径匹配
    for path in item.get("files", []):
        if DOC_PATH_PATTERNS.search(path):
            return True
    return False


def classify_contributions(prs: list, issues: list) -> tuple[list, list, list]:
    """
    将 PR/Issue 分类为：
      - doc_contribs:  文档贡献
      - code_contribs: 代码贡献
      - valuable_issues: 有价值的 Issue（最多 10 条，按互动量降序）
    """
    doc_contribs = []
    code_contribs = []

    for pr in prs:
        if is_doc_contribution(pr):
            doc_contribs.append(pr)
        else:
            code_contribs.append(pr)

    # 有价值 Issue 筛选
    valuable = []
    for issue in issues:
        labels_lower = issue.get("label_names_lower", [])
        has_valuable_label = bool(VALUABLE_LABELS.intersection(set(labels_lower)))
        if (
            issue.get("reactions", 0) >= 3
            or issue.get("comments", 0) >= 5
            or has_valuable_label
        ):
            valuable.append(issue)

    # 按互动量（反应数 + 评论数）降序，取前 10
    valuable.sort(key=lambda x: x.get("reactions", 0) + x.get("comments", 0), reverse=True)
    valuable_issues = valuable[:10]

    return doc_contribs, code_contribs, valuable_issues


# ─────────────────────── HTML 生成 ───────────────────────

def fmt_date(iso_str: Optional[str]) -> str:
    """将 ISO 8601 时间字符串格式化为 YYYY-MM-DD。"""
    if not iso_str:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso_str[:10]


def state_badge(state: str) -> str:
    """根据状态生成对应的 HTML badge。"""
    mapping = {
        "merged": ("bg-purple", "Merged"),
        "open": ("bg-success", "Open"),
        "closed": ("bg-secondary", "Closed"),
    }
    css, text = mapping.get(state.lower(), ("bg-secondary", state.capitalize()))
    return f'<span class="badge {css} me-1">{html_module.escape(text)}</span>'


def label_badge(label: str) -> str:
    """生成标签 badge HTML。"""
    return f'<span class="badge bg-label me-1">{html_module.escape(label)}</span>'


def render_card(item: dict) -> str:
    """将单个贡献/Issue 渲染为 Bootstrap 卡片 HTML。"""
    title_escaped = html_module.escape(item.get("title", "(无标题)"))
    url = item.get("url", "#")
    repo = html_module.escape(item.get("repo", ""))
    date = fmt_date(item.get("created_at", ""))
    state = item.get("state", "")
    labels = item.get("labels", [])
    reactions = item.get("reactions", 0)
    comments = item.get("comments", 0)

    label_html = "".join(label_badge(lbl) for lbl in labels)
    stats_html = ""
    if reactions or comments:
        stats_html = (
            f'<small class="text-muted ms-2">'
            f'👍 {reactions} &nbsp; 💬 {comments}'
            f'</small>'
        )

    return f"""
    <div class="col-md-6 col-lg-4 mb-3 card-item">
      <div class="card h-100 shadow-sm border-0">
        <div class="card-body">
          <h6 class="card-title">
            <a href="{url}" target="_blank" rel="noopener" class="text-decoration-none fw-bold">
              {title_escaped}
            </a>
          </h6>
          <p class="card-text text-muted small mb-2">
            <i class="bi bi-box-seam me-1"></i>{repo}
            <span class="ms-2"><i class="bi bi-calendar3 me-1"></i>{date}</span>
          </p>
          <div>
            {state_badge(state)}
            {label_html}
            {stats_html}
          </div>
        </div>
      </div>
    </div>
    """


def render_section(icon: str, title: str, items: list, section_id: str) -> str:
    """渲染一个贡献区块（含折叠/展开、搜索筛选功能）。"""
    if not items:
        cards_html = '<p class="text-muted">暂无数据</p>'
    else:
        cards_html = '<div class="row" id="cards-' + section_id + '">' + "".join(render_card(item) for item in items) + "</div>"

    return f"""
    <section class="mb-5" id="section-{section_id}">
      <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
        <h2 class="section-title mb-0">{icon} {html_module.escape(title)}
          <span class="badge bg-primary rounded-pill ms-2 align-middle">{len(items)}</span>
        </h2>
        <div class="d-flex gap-2">
          <input
            type="search"
            class="form-control form-control-sm filter-input"
            data-target="cards-{section_id}"
            placeholder="搜索…"
            style="max-width:220px"
          />
          <button
            class="btn btn-sm btn-outline-secondary toggle-btn"
            data-target="cards-{section_id}"
            onclick="toggleSection(this)"
          >折叠</button>
        </div>
      </div>
      {cards_html}
    </section>
    """


def generate_html(profile: dict, doc_contribs: list, code_contribs: list, valuable_issues: list) -> str:
    """组装完整的 HTML 页面字符串。"""
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(doc_contribs) + len(code_contribs) + len(valuable_issues)

    doc_section = render_section("📄", "文档贡献", doc_contribs, "doc")
    code_section = render_section("💻", "代码贡献", code_contribs, "code")
    issue_section = render_section("💡", "有价值的 Issue", valuable_issues, "issue")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html_module.escape(profile['name'])} - GitHub 开源贡献简历</title>
  <!-- Bootstrap 5 CDN -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" />
  <!-- Bootstrap Icons -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" />
  <style>
    :root {{
      --accent: #0d6efd;
      --purple: #6f42c1;
    }}
    body {{
      background: #f8f9fa;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .hero {{
      background: linear-gradient(135deg, #0d6efd 0%, #6f42c1 100%);
      color: #fff;
      padding: 3rem 1rem 2rem;
      text-align: center;
    }}
    .hero img {{
      width: 110px;
      height: 110px;
      border-radius: 50%;
      border: 4px solid rgba(255,255,255,.6);
      margin-bottom: 1rem;
      object-fit: cover;
    }}
    .stat-card {{
      background: rgba(255,255,255,.15);
      border-radius: 12px;
      padding: 1rem 1.5rem;
      min-width: 130px;
      backdrop-filter: blur(4px);
    }}
    .stat-card .num {{
      font-size: 2rem;
      font-weight: 700;
      line-height: 1;
    }}
    .stat-card .label {{
      font-size: .8rem;
      opacity: .85;
    }}
    .section-title {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #343a40;
    }}
    .card {{
      border-radius: 12px;
      transition: transform .15s, box-shadow .15s;
    }}
    .card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 8px 24px rgba(0,0,0,.1) !important;
    }}
    .bg-purple {{
      background-color: var(--purple) !important;
    }}
    .bg-label {{
      background-color: #e9ecef;
      color: #495057;
    }}
    footer {{
      background: #343a40;
      color: #adb5bd;
      text-align: center;
      padding: 1.5rem 1rem;
      font-size: .85rem;
    }}
    footer a {{
      color: #6ea8fe;
    }}
    .filter-input {{
      border-radius: 20px;
    }}
  </style>
</head>
<body>

<!-- ───── 头部英雄区 ───── -->
<header class="hero">
  <img src="{html_module.escape(profile['avatar_url'])}" alt="{html_module.escape(profile['name'])}" loading="lazy" />
  <h1 class="h3 fw-bold mb-1">
    <a href="{html_module.escape(profile['html_url'])}" target="_blank" rel="noopener" class="text-white text-decoration-none">
      {html_module.escape(profile['name'])}
    </a>
  </h1>
  <p class="mb-3 opacity-75">{html_module.escape(profile['bio'])}</p>
  <!-- 统计卡片 -->
  <div class="d-flex flex-wrap justify-content-center gap-3 mt-2">
    <div class="stat-card">
      <div class="num">{total}</div>
      <div class="label">总贡献</div>
    </div>
    <div class="stat-card">
      <div class="num">{len(doc_contribs)}</div>
      <div class="label">📄 文档贡献</div>
    </div>
    <div class="stat-card">
      <div class="num">{len(code_contribs)}</div>
      <div class="label">💻 代码贡献</div>
    </div>
    <div class="stat-card">
      <div class="num">{len(valuable_issues)}</div>
      <div class="label">💡 有价值 Issue</div>
    </div>
  </div>
</header>

<!-- ───── 主内容 ───── -->
<main class="container my-5">

  {doc_section}
  {code_section}
  {issue_section}

</main>

<!-- ───── 页脚 ───── -->
<footer>
  由 <a href="https://github.com/{GITHUB_USER}" target="_blank" rel="noopener">GitHub API</a>
  动态生成 · 实时数据 &nbsp;|&nbsp;
  生成时间：{generated_at}
</footer>

<!-- Bootstrap JS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
  // ── 折叠 / 展开 ──
  function toggleSection(btn) {{
    const target = document.getElementById(btn.dataset.target);
    if (!target) return;
    const hidden = target.style.display === 'none';
    target.style.display = hidden ? '' : 'none';
    btn.textContent = hidden ? '折叠' : '展开';
  }}

  // ── 实时搜索筛选 ──
  document.querySelectorAll('.filter-input').forEach(function(input) {{
    input.addEventListener('input', function() {{
      const keyword = this.value.toLowerCase();
      const container = document.getElementById(this.dataset.target);
      if (!container) return;
      container.querySelectorAll('.card-item').forEach(function(card) {{
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(keyword) ? '' : 'none';
      }});
    }});
  }});
</script>
</body>
</html>
"""


# ─────────────────────── 主流程 ───────────────────────

def main():
    print("=" * 60)
    print("  dynamic-resume · GitHub 贡献简历生成器")
    print("=" * 60)

    # 1. 构建 HTTP 会话
    session = make_session()

    # 2. 获取用户基础信息
    profile = fetch_user_profile(session)
    print(f"  用户：{profile['name']}  ({profile['login']})")

    # 3. 获取 Pull Request
    #    优先尝试 GraphQL（需要有效 Token）；失败时退回 REST Search API
    prs = []
    if GITHUB_TOKEN:
        try:
            prs = fetch_pull_requests_graphql(session)
        except Exception as exc:
            print(f"  ⚠️  GraphQL 获取 PR 失败（{exc}），切换到 REST API…")
            prs = fetch_pull_requests_rest(session)
    else:
        prs = fetch_pull_requests_rest(session)

    # 4. 获取 Issue
    issues = fetch_issues(session)

    # 5. 分类
    print("\n🔍 对贡献进行分类…")
    doc_contribs, code_contribs, valuable_issues = classify_contributions(prs, issues)
    print(f"  📄 文档贡献：{len(doc_contribs)} 条")
    print(f"  💻 代码贡献：{len(code_contribs)} 条")
    print(f"  💡 有价值 Issue：{len(valuable_issues)} 条")

    # 6. 生成 HTML
    print("\n✍️  生成 HTML 简历…")
    html_content = generate_html(profile, doc_contribs, code_contribs, valuable_issues)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  ✅ 已写入 {OUTPUT_FILE}")

    # 7. 可选：在浏览器中自动打开
    if AUTO_OPEN_BROWSER:
        abs_path = os.path.abspath(OUTPUT_FILE)
        webbrowser.open(f"file://{abs_path}")
        print("  🌐 已在浏览器中打开")

    print("\n🎉 完成！")


if __name__ == "__main__":
    main()
