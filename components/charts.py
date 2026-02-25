"""ECharts bouwers voor dashboard — omzet bar chart en kosten donut."""

from nicegui import ui


def revenue_bar_chart(data_current: list[float], data_previous: list[float],
                      jaar: int) -> ui.echart:
    """Monthly revenue bar chart with year-over-year comparison.

    Args:
        data_current: 12 monthly totals for the selected year.
        data_previous: 12 monthly totals for the previous year.
        jaar: The selected year (shown in legend).
    """
    maanden = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
               'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
    return ui.echart({
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
            'formatter': None,  # Will use default: shows both series
        },
        'legend': {'data': [str(jaar), str(jaar - 1)]},
        'grid': {'left': '3%', 'right': '4%', 'bottom': '3%', 'containLabel': True},
        'xAxis': {'type': 'category', 'data': maanden},
        'yAxis': {
            'type': 'value',
            'axisLabel': {'formatter': '\u20ac {value}'},
        },
        'series': [
            {
                'name': str(jaar),
                'type': 'bar',
                'data': data_current,
                'itemStyle': {'color': '#1976D2'},
            },
            {
                'name': str(jaar - 1),
                'type': 'bar',
                'data': data_previous,
                'itemStyle': {'color': '#E0E0E0'},
            },
        ],
    }).classes('w-full h-72')


def cost_donut_chart(data: list[dict]) -> ui.echart:
    """Cost breakdown donut chart.

    Args:
        data: list of {'categorie': str, 'totaal': float} from
              get_uitgaven_per_categorie().
    """
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
            'right': '5%',
            'top': 'center',
        },
        'series': [{
            'type': 'pie',
            'radius': ['40%', '70%'],
            'center': ['40%', '50%'],
            'avoidLabelOverlap': True,
            'itemStyle': {'borderRadius': 4, 'borderColor': '#fff', 'borderWidth': 2},
            'label': {'show': False},
            'emphasis': {
                'label': {'show': True, 'fontSize': 14, 'fontWeight': 'bold'},
            },
            'data': chart_data,
        }],
    }).classes('w-full h-72')
