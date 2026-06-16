# GitHub 发布清单

当前机器没有可用的 `git` 和 `gh` 命令。安装 GitHub Desktop 或 Git for Windows 后，在 `literature-morning-report` 目录运行以下命令。

## 本地初始化

```powershell
cd "F:\codex ducs\PhD related\literature-morning-report"
git init
git add .
git commit -m "Initial open-source literature morning report skill"
git branch -M main
```

## 创建 GitHub 仓库

方式 1：GitHub 网页

1. 打开 https://github.com/new
2. Repository name: `literature-morning-report`
3. Visibility: Public
4. 不勾选自动创建 README、.gitignore、license
5. 创建后按页面提示添加 remote 并 push

方式 2：GitHub CLI

```powershell
gh auth login
gh repo create literature-morning-report --public --source . --remote origin --push
```

## 发布前检查

```powershell
python scripts\literature_morning_report.py --profile assets\research_profile.template.yml --history reports\sent_history.tsv --journal-metrics assets\journal_metrics.template.tsv --output-dir reports --offline-sample --dry-run --date 2026-06-14
```

确认不要提交：

- `.env`
- `research_profile.yml`
- `sent_history.tsv`
- `reports/`
- 用户邮箱
- API key
- SMTP 密码
