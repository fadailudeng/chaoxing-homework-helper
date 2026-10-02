#!/usr/bin/env bash
# 首次发布到 GitHub。用法：
#   bash tools/publish_github.sh <GitHub用户名> <仓库URL>
# 例：
#   bash tools/publish_github.sh zhangsan https://github.com/zhangsan/chaoxing-homework-helper.git
#
# 这个脚本只做三件事：配身份 → 提交 → 推。推送前的安全核对（.gitignore 拦敏感文件）
# 请先跑 tools/pre_publish_check.sh 确认过。
set -euo pipefail

USER_NAME="${1:?用法: bash tools/publish_github.sh <GitHub用户名> <仓库URL>}"
REPO_URL="${2:?用法: bash tools/publish_github.sh <GitHub用户名> <仓库URL>}"

cd "$(dirname "$0")/.."

echo "==> 1/4 配置提交身份（只写本仓库，不动全局）"
git config user.name  "$USER_NAME"
git config user.email "${USER_NAME}@users.noreply.github.com"
git config --list --show-origin | grep -i "user\."

echo
echo "==> 2/4 提交前再核对一次：绝不能有敏感文件进暂存区"
if git diff --cached --name-only | grep -qE '^(data|debug)/' ; then
  echo "!!! 暂存区里有 data/ 或 debug/ 的文件，停下："
  git diff --cached --name-only | grep -E '^(data|debug)/'
  exit 1
fi
echo "    OK：暂存区没有 data/ 或 debug/ 的东西"
echo "    本次要提交：$(git diff --cached --name-only | wc -l) 个文件"

echo
echo "==> 3/4 首次提交"
git commit -q -m "$(cat <<'EOF'
学习通作业助手：一键扫全部作业 + 抓题目 + 打包给 AI

不用再一门一门点开课程 → 我的 → 作业。本地桌面程序（Edge 应用窗口，
零额外 GUI 依赖），数据全部留在自己电脑上。

- 一键扫全部课程作业，按课程分组、五态筛选、剩余时间按紧急度变色
- 一键抓待办作业的题目：题型/分值/题干/输入输出格式/示例/代码模板
- 一键把题目打包成 Markdown 丢给 AI（只整理题目，不生成答案）
- 界面上的「清理缓存」：白名单 + 保护清单 + 删除前后指纹核对，
  只清 Edge 塞进界面 profile 的组件，登录态和已扫数据绝不触碰
- 撞风控时点一下把验证码页面打开，输完自动继续

测试：99 条单测（解析器/分页/清理安全/打包边界）+ 内联 JS 语法 + 服务冒烟。
EOF
)"
git log --oneline -1

echo
echo "==> 4/4 推送"
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"
git push -u origin main

echo
echo "完成。仓库地址：${REPO_URL%.git}"
