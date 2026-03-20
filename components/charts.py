"""ECharts bouwers voor dashboard — omzet bar chart en kosten donut."""

from nicegui import ui

# Coordinated chart palette
CHART_COLORS = [
    '#0F766E',  # teal (primary)
    '#F59E0B',  # amber (accent)
    '#6366F1',  # indigo
    '#EC4899',  # pink
    '#8B5CF6',  # violet
    '#14B8A6',  # light teal
    '#F97316',  # orange
    '#64748B',  # slate
]

DONUT_COLORS = ['#0F766E', '#14B8A6', '#5EEAD4', '#99F6E4']


def revenue_bar_chart(data_current: list[float], data_previous: list[float],
                      jaar: int) -> ui.echart:
    """Monthly revenue bar chart with year-over-year comparison."""
    maanden = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
               'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
    return ui.echart({
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
        },
        'legend': {
            'data': [str(jaar), str(jaar - 1)],
            'textStyle': {'color': '#64748B'},
        },
        'grid': {'left': '3%', 'right': '4%', 'bottom': '3%', 'containLabel': True},
        'xAxis': {
            'type': 'category',
            'data': maanden,
            'axisLabel': {'color': '#64748B'},
            'axisLine': {'lineStyle': {'color': '#E2E8F0'}},
        },
        'yAxis': {
            'type': 'value',
            'axisLabel': {'formatter': '\u20ac {value}', 'color': '#64748B'},
            'splitLine': {'lineStyle': {'color': '#F1F5F9'}},
        },
        'series': [
            {
                'name': str(jaar),
                'type': 'bar',
                'data': data_current,
                'itemStyle': {'color': '#0F766E', 'borderRadius': [4, 4, 0, 0]},
            },
            {
                'name': str(jaar - 1),
                'type': 'bar',
                'data': data_previous,
                'itemStyle': {'color': '#CBD5E1', 'borderRadius': [4, 4, 0, 0]},
            },
        ],
    }).style('height: 300px; width: 100%')


def cost_donut_chart(data: list[dict]) -> ui.echart:
    """Cost breakdown donut chart — monochromatic teal palette."""
    chart_data = [
        {'value': round(d['totaal'], 2), 'name': d['categorie']}
        for d in data if d['totaal'] > 0
    ]

    return ui.echart({
        'tooltip': {
            'trigger': 'item',
            'formatter': '{b}: \u20ac {c} ({d}%)',
        },
        'legend': {
            'orient': 'vertical',
            'left': 'center',
            'bottom': '0%',
            'textStyle': {'color': '#475569', 'fontSize': 12},
            'itemWidth': 8,
            'itemHeight': 8,
            'icon': 'circle',
        },
        'color': DONUT_COLORS,
        'series': [{
            'type': 'pie',
            'radius': ['40%', '70%'],
            'center': ['50%', '40%'],
            'avoidLabelOverlap': True,
            'itemStyle': {'borderRadius': 6, 'borderColor': '#fff', 'borderWidth': 2},
            'label': {'show': False},
            'emphasis': {
                'label': {'show': True, 'fontSize': 14, 'fontWeight': 'bold'},
            },
            'data': chart_data,
        }],
    }).style('height: 280px; width: 100%')
