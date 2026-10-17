"""Dashboard and authenticated Photon 2.0 notification providers."""
import json
import os
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


class NotificationProvider(Protocol):
    def send(self, alert): ...


class LocalNotificationProvider:
    name = 'dashboard'
    def send(self, alert):
        return {'delivered':True,'channel':'dashboard','alert_id':alert['id'],'external':False}


class PhotonNotificationProvider(LocalNotificationProvider):
    name = 'photon'

    def __init__(self, api_key=None, project_id=None, agent_user_id=None, recipient=None,
                 platform=None, base_url=None, timeout=None):
        self.api_key = api_key or os.getenv('PHOTON_API_KEY','')
        self.project_id = project_id or os.getenv('PHOTON_PROJECT_ID','')
        self.agent_user_id = agent_user_id or os.getenv('PHOTON_AGENT_USER_ID','')
        self.recipient = recipient or os.getenv('PHOTON_RECIPIENT','')
        self.platform = platform or os.getenv('PHOTON_PLATFORM','imessage')
        self.base_url = (base_url or os.getenv('PHOTON_API_BASE','https://api.photon.codes')).rstrip('/')
        self.timeout = float(timeout or os.getenv('PHOTON_TIMEOUT_SECONDS','15'))

    @property
    def configured(self):
        return all((self.api_key,self.project_id,self.agent_user_id,self.recipient))

    def _post(self, path, body, idempotency_key=None):
        request = Request(
            f'{self.base_url}/v1/projects/{self.project_id}{path}',
            data=json.dumps(body).encode(), method='POST', headers={
                'Authorization':'Bearer ' + self.api_key,
                'Content-Type':'application/json',
                'Idempotency-Key':idempotency_key or str(uuid4()),
            })
        with urlopen(request,timeout=self.timeout) as response:
            payload = json.load(response)
            return response.status,payload

    @staticmethod
    def _message(alert):
        consequence = alert.get('consequence') or alert.get('cause') or 'Review the proposed supply scenario.'
        link = alert.get('deep_link','/#scenarios')
        return (f"{alert.get('title','Supply scenario needs review')}\n"
                f"Cause: {alert.get('cause','Planning change detected')}\n"
                f"Projected consequence: {consequence}\n"
                f"Review status: {alert.get('review_status','proposed')}\n"
                f"Open: {link}")

    def send(self, alert):
        base = {'delivered':False,'accepted':False,'channel':'photon','alert_id':alert['id'],'external':True}
        if not self.configured:
            return {**base,'reason':'Photon credentials or recipient are not configured; alert remains visible in dashboard.'}
        try:
            _,user = self._post('/users',{'platform':self.platform,'handle':self.recipient},f"{alert['id']}:user")
            _,space = self._post('/spaces',{'platform':self.platform,'participantIds':[self.agent_user_id,user['id']]},f"{alert['id']}:space")
            status,message = self._post('/messages',{
                'spaceId':space['id'],'senderId':self.agent_user_id,
                'content':{'type':'text','format':'plain','text':self._message(alert)},
            },f"{alert['id']}:message")
            # Photon documents 202 as accepted, distinct from confirmed delivery.
            return {**base,'accepted':status in (200,201,202),'delivered':status in (200,201),
                    'delivery_status':'accepted' if status==202 else 'delivered',
                    'message_id':message.get('id'),'space_id':space.get('id'),'recipient_user_id':user.get('id')}
        except HTTPError as exc:
            return {**base,'reason':f'Photon HTTP {exc.code}','status':exc.code}
        except Exception as exc:
            return {**base,'reason':type(exc).__name__}

    def reply(self, *, space_id, text, reply_id):
        base = {'delivered':False,'accepted':False,'channel':'photon','external':True,'reply_id':reply_id}
        if not self.configured:
            return {**base,'reason':'Photon credentials are not configured'}
        try:
            status,message = self._post('/messages',{
                'spaceId':space_id,'senderId':self.agent_user_id,
                'content':{'type':'text','format':'plain','text':str(text)[:8000]},
            },f'{reply_id}:reply')
            return {**base,'accepted':status in (200,201,202),'delivered':status in (200,201),
                    'delivery_status':'accepted' if status==202 else 'delivered','message_id':message.get('id'),'space_id':space_id}
        except HTTPError as exc:
            return {**base,'reason':f'Photon HTTP {exc.code}','status':exc.code}
        except Exception as exc:
            return {**base,'reason':type(exc).__name__}


def configured_notifications():
    return PhotonNotificationProvider() if os.getenv('PHOTON_ENABLED','false').lower() == 'true' else LocalNotificationProvider()
