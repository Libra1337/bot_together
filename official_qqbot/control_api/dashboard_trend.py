"""Small SVG time-series view backed by non-overlapping database buckets."""
import html
import json
import math


def render_trend(trend: dict) -> str:
    labels, series = trend['labels'], trend['series']
    maximum = max([count for values in series.values() for count in values] + [1])
    tick = max(1, math.ceil(maximum / 4))
    ceiling = tick * 4
    x = lambda index: 48 + index * 648 / max(1, len(labels) - 1)
    y = lambda count: 264 - count / ceiling * 232
    grid = ''.join(f'<line class="mc-chart-grid" x1="48" x2="696" y1="{y(tick*i):.2f}" y2="{y(tick*i):.2f}"/><text class="mc-chart-axis" x="36" y="{y(tick*i)+5:.2f}" text-anchor="end">{tick*i}</text>' for i in range(5))
    indices = sorted({round(index * (len(labels) - 1) / 4) for index in range(5)})
    axis = ''.join(f'<text class="mc-chart-axis" x="{x(index):.2f}" y="292" text-anchor="{ "start" if index == 0 else "end" if index == len(labels)-1 else "middle"}">{labels[index][6:] if trend["interval"] != "day" else labels[index][:5]}</text>' for index in indices)
    lines = ''.join(f'<polyline class="mc-chart-line series-{name}" fill="none" points="' + ' '.join(f'{x(index):.2f},{y(count):.2f}' for index, count in enumerate(values)) + '"/>' for name, values in series.items())
    points = []
    rows = []
    readings = []
    for index, label in enumerate(labels):
        reading = label + ' · ' + ' / '.join(f'{name.upper()} {values[index]:,} 次' for name, values in series.items())
        readings.append(reading)
        left = 48 if index == 0 else (x(index - 1) + x(index)) / 2
        right = 696 if index == len(labels) - 1 else (x(index) + x(index + 1)) / 2
        points.append(f'<rect class="mc-chart-hit" x="{left:.2f}" y="24" width="{right-left:.2f}" height="244" data-trend-index="{index}"><title>{html.escape(reading)}</title></rect>')
        rows.append('<tr><td>' + label + '</td>' + ''.join(f'<td class="numeric">{values[index]:,}</td>' for values in series.values()) + '</tr>')
    controls = ''.join(f'<a href="/dashboard?interval={value}" class="{ "is-active" if value == trend["interval"] else ""}"' + (' aria-current="page"' if value == trend['interval'] else '') + f'>{title}</a>' for value, title in [('minute', '每分钟'), ('hour', '每小时'), ('day', '每天')])
    data = html.escape(json.dumps(readings, ensure_ascii=False), quote=True)
    period = {'minute': '最近 60 个分钟', 'hour': '最近 24 个小时', 'day': '最近 7 个自然日'}[trend['interval']]
    return f'''<div class="panel-head"><div><h2>成功获取趋势</h2><p>{period} · 北京时间</p></div><span>{trend['total']:,} 次</span></div>
      <div class="mc-chart-controls"><nav class="mc-chart-ranges" aria-label="趋势统计粒度">{controls}</nav><a class="button ghost" href="/dashboard?interval={trend['interval']}">刷新</a></div>
      <div class="mc-chart-legend">{''.join(f'<span class="series-{name}"><i aria-hidden="true"></i>{name.upper()}</span>' for name in series)}</div>
      <div class="mc-trend" data-trend-readings="{data}">
        <svg class="mc-trend-chart" viewBox="0 0 720 310" role="img" aria-label="各资源按时间分桶的成功获取次数；下方可查看逐项数据">{grid}{axis}{lines}{''.join(points)}</svg>
        <label class="sr-only" for="trend-point">查看时间点</label><input class="mc-trend-slider" id="trend-point" type="range" min="0" max="{len(labels)-1}" value="{len(labels)-1}" aria-describedby="trend-reading">
        <output class="mc-chart-readout" id="trend-reading" for="trend-point">{html.escape(readings[-1])}</output>
      </div>
      <p class="mc-inline-note">{trend['start']} — {trend['as_of']}，当前时间段尚未结束。</p>
      <details class="mc-chart-details"><summary>查看分时数据</summary><div class="table-wrap"><table><thead><tr><th scope="col">北京时间</th>{''.join(f'<th scope="col" class="numeric">{name.upper()}</th>' for name in series)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>'''
