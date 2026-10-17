"""ICS, Google Calendar, and Microsoft Graph milestone providers."""
import hashlib
import json
import os
from datetime import date, timedelta
from typing import Protocol
from urllib.parse import quote
from urllib.request import Request, urlopen


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


def milestone_events(scenario):
    if scenario.get('status') != 'approved':
        raise ValueError('Only approved milestones can be synchronized')
    for shipment in scenario['shipments']:
        for milestone in shipment['milestones']:
            day = date.fromisoformat(milestone['projected_date'][:10])
            yield {'key':f"{scenario['id']}:{milestone['id']}",'title':f"{shipment['country_name']} — {milestone['label']}",
                   'description':f"Cleared for Takeoff approved scenario {scenario['id']}. Decision support; verify source requirements.",
                   'start':day.isoformat(),'end':(day+timedelta(days=1)).isoformat()}


class RESTCalendarProvider:
    name = 'calendar'
    def __init__(self, token=None, timeout=None):
        self.token = token or ''
        self.timeout = float(timeout or os.getenv('CALENDAR_TIMEOUT_SECONDS','15'))

    def _post(self, url, body):
        request = Request(url,data=json.dumps(body).encode(),method='POST',headers={
            'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with urlopen(request,timeout=self.timeout) as response:
            return response.status,json.load(response)


class GoogleCalendarProvider(RESTCalendarProvider):
    name = 'google'
    def __init__(self, token=None, calendar_id=None, timeout=None):
        super().__init__(token or os.getenv('GOOGLE_CALENDAR_ACCESS_TOKEN',''),timeout)
        self.calendar_id = calendar_id or os.getenv('GOOGLE_CALENDAR_ID','primary')

    def sync(self, scenario):
        if not self.token: raise ValueError('Google Calendar access token is not configured')
        created=[]
        for event in milestone_events(scenario):
            event_id=hashlib.sha256(event['key'].encode()).hexdigest()[:32]
            status,result=self._post(f"https://www.googleapis.com/calendar/v3/calendars/{quote(self.calendar_id,safe='')}/events",{
                'id':event_id,'summary':event['title'],'description':event['description'],
                'start':{'date':event['start']},'end':{'date':event['end']},
                'extendedProperties':{'private':{'clearedScenarioId':scenario['id']}}})
            created.append({'id':result.get('id'),'link':result.get('htmlLink'),'status':status})
        return {'provider':self.name,'created':len(created),'events':created}


class OutlookCalendarProvider(RESTCalendarProvider):
    name = 'outlook'
    def __init__(self, token=None, timeout=None):
        super().__init__(token or os.getenv('MICROSOFT_GRAPH_ACCESS_TOKEN',''),timeout)

    def sync(self, scenario):
        if not self.token: raise ValueError('Microsoft Graph access token is not configured')
        created=[]
        for event in milestone_events(scenario):
            status,result=self._post('https://graph.microsoft.com/v1.0/me/calendar/events',{
                'subject':event['title'],'body':{'contentType':'text','content':event['description']},
                'isAllDay':True,'start':{'dateTime':event['start']+'T00:00:00','timeZone':'UTC'},
                'end':{'dateTime':event['end']+'T00:00:00','timeZone':'UTC'}})
            created.append({'id':result.get('id'),'link':result.get('webLink'),'status':status})
        return {'provider':self.name,'created':len(created),'events':created}


def configured_calendar(name):
    if name == 'google': return GoogleCalendarProvider()
    if name == 'outlook': return OutlookCalendarProvider()
    return ICSCalendarProvider()
