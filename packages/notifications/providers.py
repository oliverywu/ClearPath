"""Photon intentionally isolated until its integration contract is available."""
import os
from typing import Protocol


class NotificationProvider(Protocol):
    def send(self, alert): ...


class LocalNotificationProvider:
    name = 'dashboard'
    def send(self, alert):
        return {'delivered':True,'channel':'dashboard','alert_id':alert['id'],'external':False}


class PhotonNotificationProvider(LocalNotificationProvider):
    name = 'photon-unconfigured'
    def send(self, alert):
        return {'delivered':False,'channel':'photon','alert_id':alert['id'],'reason':'Photon provider contract is not configured; alert remains visible in dashboard.'}


def configured_notifications():
    return PhotonNotificationProvider() if os.getenv('PHOTON_ENABLED','false').lower() == 'true' else LocalNotificationProvider()
