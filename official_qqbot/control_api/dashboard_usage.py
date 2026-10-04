"""Server-rendered resource evidence, using actual database aggregates."""
import html
from urllib.parse import urlencode


RANGES = [("second", "近 1 秒"), ("minute", "近 1 分钟"), ("hour", "近 1 小时"),
          ("day", "近 24 小时"), ("month", "近 30 天"), ("year", "近 365 天")]
UNITS = {"min": "分钟", "hour": "小时", "day": "天", "month": "30 天", "quarter": "90 天", "year": "365 天"}
NAMES = {"163": "163 小号", "4399": "4399 账号", "nfa": "NFA Token"}


def rule_list(stats, form=None):
    form = form or {}
    rows = []
    for item in stats:
        resource = item['resource']
        editing = form.get('resource') == resource
        count = form.get('limit_count', item['limit_count'] or 1) if editing else item['limit_count'] or 1
        unit = form.get('window_unit', item['window_unit'] or 'day') if editing else item['window_unit'] or 'day'
        rule = f'{item["limit_count"]:,} 次 / {UNITS.get(item["window_unit"], "")}' if item['limit_count'] else '未设置'
        options = ''.join(f'<option value="{key}"{" selected" if key == unit else ""}>{label}</option>' for key, label in [('min','1 分钟'),('hour','1 小时'),('day','1 天'),('month','30 天'),('quarter','90 天'),('year','365 天')])
        rows.append(f'''<details class="mc-rule" id="rule-{resource}"{' open' if editing else ''}>
          <summary><span class="mc-resource-title"><strong>{esc(NAMES[resource])}</strong></span><span class="mc-rule-value">{esc(rule)}</span><span class="mc-edit-label">编辑规则</span></summary>
          <form class="mc-rule-form" method="post" action="/dashboard/resource-limits">
            <input type="hidden" name="resource" value="{resource}">
            <div><label for="count-{resource}">每人可获取次数</label><input id="count-{resource}" name="limit_count" type="number" min="1" max="1000000" value="{esc(count)}" required></div>
            <div><label for="window-{resource}">滚动周期</label><select id="window-{resource}" name="window_unit">{options}</select></div>
            <button type="submit">保存规则<span class="sr-only"> · {esc(NAMES[resource])}</span></button>
          </form>
        </details>''')
    return '<div class="mc-rule-list">' + ''.join(rows) + '</div>'


def esc(value):
    return html.escape(str(value), quote=True)


def short_time(value):
    return value[5:10] + ' ' + value[11:] if len(value) >= 19 else value


def usage_summary(stats):
    rows = []
    for item in stats:
        resource = item["resource"]
        counts = item["counts"]
        rule = f'{item["limit_count"]:,} 次 / {UNITS.get(item["window_unit"], item["window_unit"])}' if item["limit_count"] else "未设置"
        rows.append(f'<tr><td><strong class="resource-name">{esc(resource.upper())}</strong><span class="cell-note">{esc(NAMES.get(resource, resource))}</span></td>'
                    + "".join(f'<td class="numeric">{int(counts.get(key, 0)):,}</td>' for key, _ in RANGES)
                    + f'<td>{rule}<span class="cell-note">每位用户</span></td></tr>')
    headers = '<th scope="col">资源</th>' + ''.join(f'<th class="numeric" scope="col">{label}</th>' for _, label in RANGES) + '<th scope="col">个人限额</th>'
    return f'<div class="table-wrap"><table class="usage-summary-table"><caption class="sr-only">全部用户的滚动时间窗口获取次数与个人限额</caption><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def duration(seconds):
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    if seconds < 86400:
        return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分"
    return f"{seconds // 86400} 天 {(seconds % 86400) // 3600} 小时"


def user_usage_table(result):
    rows = []
    for item in result["items"]:
        user = esc(item["user_key"])
        limit, used = int(item["limit"]), int(item["used"])
        status = "已达限额" if item["blocked"] else "可继续获取"
        klass = " is-blocked" if item["blocked"] else ""
        rows.append(f'''<tr>
          <td><code title="{user}">{user}</code></td>
          <td><strong>{esc(item['resource'].upper())}</strong><span class="cell-note">每{UNITS.get(item['window_unit'], esc(item['window_unit']))}</span></td>
          <td class="numeric"><div class="usage-meter"><span class="meter-caption">{used:,} / {limit:,}</span>
          <progress value="{min(used, limit)}" max="{limit}" aria-label="{user} 已用 {used} 次，限额 {limit} 次"></progress></div></td>
          <td class="numeric">{item['remaining']:,}</td>
          <td><span class="status-label{klass}">{status}</span></td>
          <td>{duration(item['reset_after'])}</td>
          <td class="numeric">{esc(short_time(item['latest']))}</td>
        </tr>''')
    if not rows:
        rows.append('<tr><td colspan="7" class="empty">当前筛选下暂无有效用量。<span class="cell-note">用户成功获取资源后，会在对应的限额周期内显示。</span></td></tr>')
    return '''<div class="table-wrap"><table><caption class="sr-only">每位用户在当前滚动限额周期内的用量</caption>
    <thead><tr><th scope="col">用户 OpenID</th><th scope="col">资源 / 周期</th><th scope="col" class="numeric">已用 / 限额</th>
    <th scope="col" class="numeric">剩余次数</th><th scope="col">状态</th><th scope="col">下次释放</th><th scope="col" class="numeric">最近获取 · 北京时间</th></tr></thead>
    <tbody>''' + ''.join(rows) + '</tbody></table></div>'


def filters(resource, query):
    options = ''.join(f'<option value="{key}"{" selected" if key == resource else ""}>{label}</option>' for key, label in [("", "全部资源"), ("163", "163"), ("4399", "4399"), ("nfa", "NFA")])
    return f'''<form class="table-toolbar" method="get" action="/dashboard/limits">
      <div><label for="usage-resource">资源</label><select id="usage-resource" name="resource">{options}</select></div>
      <div><label for="usage-query">查找用户</label><input id="usage-query" name="q" value="{esc(query)}" placeholder="输入 OpenID" maxlength="128" type="search"></div>
      <button type="submit">筛选用量</button><a class="button ghost" href="/dashboard/limits#user-usage">清除筛选</a>
    </form>'''


def pagination(result, resource, query):
    controls = []
    for label, page in [("上一页", result["page"] - 1), ("下一页", result["page"] + 1)]:
        if 1 <= page <= result["pages"]:
            url = '/dashboard/limits?' + urlencode({"resource": resource, "q": query, "page": page}) + '#user-usage'
            controls.append(f'<a class="button ghost" href="{esc(url)}">{label}</a>')
        else:
            controls.append(f'<button class="ghost" disabled>{label}</button>')
    return f'<div class="mc-table-foot"><span>共 {result["total"]:,} 条 · 第 {result["page"]} / {result["pages"]} 页 · 每页 20 条</span><div class="actions">{"".join(controls)}</div></div>'
