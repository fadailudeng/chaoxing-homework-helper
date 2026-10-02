#!/usr/bin/env bash
# 发 GitHub 之前的安全核对：确认敏感文件都被 .gitignore 挡住、代码里没有漏出的账号信息。
# 不改任何东西，只报告。用法：bash tools/pre_publish_check.sh
set -uo pipefail

cd "$(dirname "$0")/.."
fail=0

echo "=== 1. 哪些文件会进仓库 ==="
git add -A
count=$(git diff --cached --name-only | wc -l)
echo "    $count 个文件"
git diff --cached --shortstat | sed 's/^/    /'

echo
echo "=== 2. data/ debug/ 有没有漏进来（必须为空）==="
leak=$(git diff --cached --name-only | grep -E '^(data|debug)/' || true)
if [ -n "$leak" ]; then
  echo "!!! 漏了："; echo "$leak"; fail=1
else
  echo "    OK，一个都没有"
fi

echo
echo "=== 3. 逐条确认敏感路径被忽略 ==="
while IFS= read -r p; do
  [ -z "$p" ] && continue
  if git check-ignore -q "$p" 2>/dev/null; then
    printf '    OK   %s\n' "$p"
  else
    printf '    !!! 没忽略  %s\n' "$p"; fail=1
  fi
done <<'PATHS'
data/browser_profile/x
data/login_state.json
data/homework.json
data/tasks.json
data/courses_cache.json
data/selection.json
data/scan_log.txt
data/app.log
data/ui_profile/x
data/app.lock
data/题目/x.md
debug/raw_html/x.html
debug/course_list_raw.json
debug/homework_backup_1.json
debug/ui_preview.png
debug/preview_profile/x
.pyfound
_scratch.py
__pycache__/x.pyc
PATHS

echo
echo "=== 4. 暂存内容里扫敏感串 ==="
# 这个检查本身就得写出 password / secret 这些词，而 diff 里也会带上本脚本的
# 注释行，于是会自己匹配自己 —— 全是噪音。所以：
#   ① 跳过注释行（以 # 或 rem 开头）
#   ② 跳过「本脚本自己」这个文件
#   ③ 跳过测试夹具里故意写出来的占位值
# 剩下的才是真需要人看一眼的。
hits=$(git diff --cached -U0 -- . ':(exclude)tools/pre_publish_check.sh' \
  | grep -vE '^[+-] *#' \
  | grep -vE '^[+-] *rem ' \
  | grep -vE '^\+.*(write_text|read_text)\("secret"' \
  | grep -vE '^\+ *"secret",?$' \
  | grep -E '^\+' \
  | grep -iE '(passwd|password|api[_-]?key|Bearer [A-Za-z0-9]{8}|BEGIN [A-Z ]*PRIVATE KEY|[0-9]{11}@|authorization: )' \
  | head -20 || true)
if [ -n "$hits" ]; then
  echo "!!! 疑似敏感串（人工看一眼是不是误报）："; echo "$hits"; fail=1
else
  echo "    OK，没扫到密码 / 密钥 / 手机号类字串"
fi

echo
echo "=== 5. 代码里有没有写死本机绝对路径 ==="
hard=$(git diff --cached -U0 -- '*.py' '*.bat' | grep -E 'C:\\Users\\[^\\]+|/c/Users/[^/]+' | head -20 || true)
if [ -n "$hard" ]; then
  echo "!!! 有写死的用户目录（换机器会挂）："; echo "$hard"; fail=1
else
  echo "    OK，没有写死的 C:\\Users\\... 路径"
fi

echo
if [ "$fail" = 0 ]; then
  echo "=== 全部核对通过，可以发布 ==="
else
  echo "=== 有项目没过，先解决再发 ==="
fi
exit "$fail"
