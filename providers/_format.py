from datetime import datetime

WEEKDAYS_PT = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']


def format_when(local_dt: datetime, include_time: bool = True) -> str:
    """Formato amigável da data/hora:
    - mesmo dia → 'hoje [HH:MM]'
    - amanhã    → 'amanhã [HH:MM]'
    - até 7 dias → 'sexta [HH:MM]'
    - além     → 'dd/mm [HH:MM]'
    """
    today = datetime.now().astimezone().date()
    delta_days = (local_dt.date() - today).days
    time_str = local_dt.strftime('%H:%M') if include_time else ''
    sep = ' ' if time_str else ''

    if delta_days == 0:
        head = 'hoje'
    elif delta_days == 1:
        head = 'amanhã'
    elif 0 < delta_days < 7:
        head = WEEKDAYS_PT[local_dt.weekday()]
    else:
        head = local_dt.strftime('%d/%m')

    return f'{head}{sep}{time_str}'
