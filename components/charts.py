"""ECharts bouwers voor dashboard — omzet, kosten donut."""

from nicegui import ui

DONUT_COLORS = [
    '#0F766E',  # teal-700
    '#14B8A6',  # teal-500
    '#2DD4BF',  # teal-400
    '#5EEAD4',  # teal-300
    '#99F6E4',  # teal-200
    '#0D9488',  # teal-600
    '#115E59',  # teal-800
    '#CCFBF1',  # teal-100
    '#134E4A',  # teal-900
    '#F0FDFA',  # teal-50
]


def revenue_bar_chart(data_current: list[float], data_previous: list[float],
                      jaar: int) -> ui.echart:
    """Monthly revenue grouped bar chart with year-over-year comparison."""
    maanden = ['Jan', 'Feb', 'Mrt', 'Apr', 'Mei', 'Jun',
               'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
    return ui.echart({
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
        },
        'legend': {
            'data': [str(jaar), str(jaar - 1)],
            'right': 0, 'top': 0,
            'textStyle': {'color': '#94A3B8', 'fontSize': 11},
            'itemWidth': 14, 'itemHeight': 10,
        },
        'grid': {
            'left': '3%', 'right': '3%', 'bottom': '3%', 'top': 36,
            'containLabel': True,
        },
        'xAxis': {
            'type': 'category',
            'data': maanden,
            'axisLabel': {'color': '#94A3B8', 'fontSize': 11},
            'axisLine': {'show': False},
            'axisTick': {'show': False},
        },
        'yAxis': {
            'type': 'value',
            'axisLabel': {'formatter': '\u20ac {value}',
                          'color': '#94A3B8', 'fontSize': 11},
            'splitLine': {'lineStyle': {'color': '#F1F5F9'}},
            'axisLine': {'show': False},
            'axisTick': {'show': False},
        },
        'series': [
            {
                'name': str(jaar),
                'type': 'bar',
                'data': [round(v) for v in data_current],
                'barMaxWidth': 48,
                'barGap': '15%',
                'barCategoryGap': '30%',
                'itemStyle': {'color': '#0F766E',
                              'borderRadius': [4, 4, 0, 0]},
            },
            {
                'name': str(jaar - 1),
                'type': 'bar',
                'data': [round(v) for v in data_previous],
                'barMaxWidth': 48,
                'itemStyle': {'color': '#E2E8F0',
                              'borderRadius': [4, 4, 0, 0]},
            },
        ],
    }).style('height: 360px; width: 100%')


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
            'itemStyle': {'borderRadius': 6, 'borderColor': '#fff',
                          'borderWidth': 2},
            'label': {'show': False},
            'emphasis': {
                'label': {'show': True, 'fontSize': 14,
                          'fontWeight': 'bold'},
            },
            'data': chart_data,
        }],
    }).style('height: 280px; width: 100%')
