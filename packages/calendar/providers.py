"""User-triggered calendar export. Provider failure never updates a scenario."""
from datetime import date, timedelta
from typing import Protocol


class CalendarProvider(Protocol):
    def export(self, scenario): ...
    def sync(self, scenario): ...


def escape(value):
    return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')


def fold(line):
    result, current = [], ''
    for char in line:
        if len((current + char).encode('utf-8')) > 73:
            result.append(current)
            current = ' '
        current += char
    result.append(current)
    return '\r\n'.join(result)


class ICSCalendarProvider:
    def export(self, scenario):
        if scenario.get('status') != 'approved':
            raise ValueError('Only approved milestones can be exported')
        lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Cleared for Takeoff//Milestones//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH']
        stamp = scenario['generated_at'][:19].replace('-','').replace(':','') + 'Z'
        for shipment in scenario['shipments']:
            for milestone in shipment['milestones']:
                day = date.fromisoformat(milestone['projected_date'][:10])
                lines += ['BEGIN:VEVENT',f"UID:{escape(scenario['id'])}-{escape(milestone['id'])}@cleared.local",f'DTSTAMP:{stamp}',f'DTSTART;VALUE=DATE:{day:%Y%m%d}',f'DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}',f"SUMMARY:{escape(shipment['country_name'])} — {escape(milestone['label'])}",f"DESCRIPTION:{escape('Approved scenario ' + scenario['id'] + '. Decision support; verify all source requirements.')}",'END:VEVENT']
        lines += ['END:VCALENDAR']
        return '\r\n'.join(fold(line) for line in lines) + '\r\n'

    def sync(self, scenario):
        raise ValueError('No calendar account connected. Download the ICS file and import into your calendar.')
