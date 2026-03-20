"""ECharts bouwers voor dashboard — omzet, kosten donut."""

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


def revenue_chart(data_current: list[float], data_previous: list[float],
                  jaar: int) -> ui.echart:
    """Monthly revenue area chart with year-over-year comparison.

    Current year: solid teal area with gradient fill.
    Previous year: dashed grey line (no fill) — context without competition.
    """
    maanden = ['Jan', 'Feb', 'Mrt', 'Apr', 'Mei', 'Jun',
               'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']

    # For current year: only show data points that have values
    # (don't draw a line to zero for future months)
    has_data = [i for i, v in enumerate(data_current) if v > 0]
    last_data_month = max(has_data) if has_data else -1

    # Current year data: None for months without data (creates gap)
    current_display = [
        round(v) if i <= last_data_month and v > 0 else None
        for i, v in enumerate(data_current)
    ]
    # Previous year: always show full year as context
    previous_display = [round(v) for v in data_previous]

    return ui.echart({
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'cross', 'label': {'show': False}},
        },
        'legend': {
            'data': [str(jaar), str(jaar - 1)],
            'right': 0, 'top': 0,
            'textStyle': {'color': '#64748B', 'fontSize': 12},
            'itemWidth': 16, 'itemHeight': 2,
        },
        'grid': {'left': 48, 'right': 16, 'bottom': 28, 'top': 36},
        'xAxis': {
            'type': 'category',
            'data': maanden,
            'axisLabel': {'color': '#94A3B8', 'fontSize': 11},
            'axisLine': {'show': False},
            'axisTick': {'show': False},
            'boundaryGap': False,
        },
        'yAxis': {
            'type': 'value',
            'axisLabel': {
                'color': '#94A3B8', 'fontSize': 11,
                'formatter': ':jsFunc:(v) => "€ " + v.toLocaleString("nl-NL")',
            },
            'splitLine': {'lineStyle': {'color': '#F1F5F9'}},
            'axisLine': {'show': False},
            'axisTick': {'show': False},
        },
        'series': [
            {
                'name': str(jaar),
                'type': 'line',
                'data': current_display,
                'smooth': 0.3,
                'symbol': 'circle',
                'symbolSize': 7,
                'showSymbol': True,
                'connectNulls': False,
                'lineStyle': {'width': 3, 'color': '#0F766E'},
                'itemStyle': {'color': '#0F766E', 'borderWidth': 2,
                              'borderColor': '#fff'},
                'areaStyle': {
                    'color': {
                        'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                        'colorStops': [
                            {'offset': 0, 'color': 'rgba(15,118,110,0.18)'},
                            {'offset': 1, 'color': 'rgba(15,118,110,0)'},
                        ],
                    },
                },
            },
            {
                'name': str(jaar - 1),
                'type': 'line',
                'data': previous_display,
                'smooth': 0.3,
                'symbol': 'none',
                'lineStyle': {'width': 1.5, 'color': '#CBD5E1',
                              'type': 'dashed'},
            },
        ],
    }).style('height: 300px; width: 100%')


# Keep old name as alias for backward compatibility
revenue_bar_chart = revenue_chart


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
