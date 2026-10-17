"""Explicit response contracts for the browser-facing /api surface.

Schemas are written in a small JSON Schema subset (type, required, properties,
items, enum, nullable via a type list, additionalProperties) and checked by a
dependency-free validator. Every frontend response is validated before it leaves
the API (see apps.api.frontend.respond), so a contract drift fails loudly in tests
instead of silently breaking a screen.
"""

DATE = {'type': 'string', 'pattern': 'date'}
DATE_OR_NULL = {'type': ['string', 'null'], 'pattern': 'date'}
DATETIME = {'type': 'string'}
STR = {'type': 'string'}
STR_OR_NULL = {'type': ['string', 'null']}
INT = {'type': 'integer'}
NUM = {'type': 'number'}
BOOL = {'type': 'boolean'}

RISK_STATUS = {'type': 'string', 'enum': ['on_track', 'at_risk', 'blocked', 'no_shipment']}
WARNING_STATUS = {'type': 'string', 'enum': ['open', 'in_review', 'resolved']}
EVIDENCE_STATUS = {'type': 'string', 'enum': ['needs_review', 'verified', 'retired', 'synthetic']}
PLAN_STATUS = {'type': 'string', 'enum': ['proposed', 'approved', 'rejected', 'superseded']}
SEVERITY = {'type': 'string', 'enum': ['critical', 'high', 'medium', 'low']}
PROVENANCE = {'type': 'string', 'enum': ['live', 'sample', 'modeled', 'synthetic', 'needs_review']}

DELIVERY_RANGE = {'type': 'object', 'required': ['best', 'likely', 'worst'],
                  'properties': {'best': DATE, 'likely': DATE, 'worst': DATE}}
SHIP_BY = {'type': 'object', 'required': ['likely', 'safe'], 'properties': {'likely': DATE, 'safe': DATE}}

SHIPMENT = {
    'type': 'object',
    'required': ['id', 'country', 'countryName', 'study', 'kit', 'origin', 'destination', 'status', 'slackDays',
                 'targetDelivery', 'projectedDelivery', 'labelGroup', 'route', 'deliveryRange', 'shipBy',
                 'worstCaseSlackDays', 'currentPlanId', 'proposalIds', 'provenance'],
    'properties': {
        'id': STR, 'country': STR, 'countryName': STR, 'study': STR, 'kit': STR,
        'origin': STR, 'destination': STR, 'status': RISK_STATUS, 'slackDays': INT,
        'targetDelivery': DATE, 'projectedDelivery': DATE_OR_NULL, 'labelGroup': STR,
        'route': {'type': 'object', 'required': ['id', 'name'], 'properties': {'id': STR, 'name': STR, 'gatewayAirport': STR_OR_NULL}},
        'deliveryRange': DELIVERY_RANGE, 'shipBy': SHIP_BY, 'worstCaseSlackDays': INT,
        'currentPlanId': STR, 'proposalIds': {'type': 'array', 'items': STR}, 'provenance': PROVENANCE,
        'planningProvenance': PROVENANCE,
    },
}

EVIDENCE = {
    'type': 'object',
    'required': ['id', 'status', 'title', 'url', 'excerpt', 'sourceTier', 'jurisdiction'],
    'properties': {'id': STR, 'status': EVIDENCE_STATUS, 'title': STR, 'url': STR_OR_NULL, 'excerpt': STR_OR_NULL,
                   'sourceTier': STR_OR_NULL, 'jurisdiction': STR_OR_NULL, 'requirementKey': STR_OR_NULL},
}

PREVIEW_ROW = {'type': 'object', 'required': ['shipmentId', 'before', 'after'],
               'properties': {'shipmentId': STR, 'before': {'type': 'object'}, 'after': {'type': 'object'}}}

OPTION = {
    'type': 'object',
    'required': ['number', 'key', 'title', 'proposalId', 'status', 'recommended', 'feasible', 'preview'],
    'properties': {'number': INT, 'key': STR, 'title': STR, 'description': STR_OR_NULL, 'tradeoffs': STR_OR_NULL,
                   'proposalId': STR, 'status': PLAN_STATUS, 'recommended': BOOL,
                   'preview': {'type': 'array', 'items': PREVIEW_ROW}, 'costDelta': NUM, 'feasible': BOOL},
}

WARNING = {
    'type': 'object',
    'required': ['id', 'eventId', 'kind', 'country', 'countryName', 'requirement', 'summary', 'study',
                 'shipmentsAffected', 'severity', 'createdAt', 'status', 'recommendedAction', 'source',
                 'shipmentIds', 'proposalId', 'evidenceStatus', 'provenance'],
    'properties': {
        'id': STR, 'eventId': STR, 'kind': STR, 'country': STR, 'countryName': STR, 'requirement': STR,
        'summary': STR, 'study': STR, 'shipmentsAffected': INT, 'severity': SEVERITY, 'createdAt': DATETIME,
        'status': WARNING_STATUS, 'recommendedAction': STR, 'source': STR, 'shipmentIds': {'type': 'array', 'items': STR},
        'proposalId': STR_OR_NULL, 'evidenceStatus': EVIDENCE_STATUS, 'provenance': PROVENANCE,
    },
}

WARNING_DETAIL = {
    **WARNING,
    'required': WARNING['required'] + ['evidence', 'options', 'currentPlan', 'audit'],
    'properties': {**WARNING['properties'], 'evidence': {'type': 'array', 'items': EVIDENCE},
                   'options': {'type': 'array', 'items': OPTION}, 'currentPlan': {'type': 'object'},
                   'audit': {'type': 'array'}},
}

CARD = {'type': ['object', 'null']}
MESSAGE = {
    'type': 'object', 'required': ['id', 'from', 'sentAt'],
    'properties': {'id': STR, 'from': {'type': 'string', 'enum': ['me', 'max']}, 'sentAt': DATETIME, 'text': STR,
                   'card': CARD, 'links': {'type': 'array'}, 'quickReplies': {'type': 'array', 'items': STR}, 'caption': STR},
}
CHAT = {
    'type': 'object', 'required': ['id', 'name', 'role', 'initial', 'unread', 'updatedAt', 'lastMessage', 'links', 'canApprove'],
    'properties': {'id': STR, 'name': STR, 'role': STR, 'initial': STR, 'unread': INT, 'updatedAt': DATETIME,
                   'lastMessage': STR, 'links': {'type': 'array', 'items': STR}, 'canApprove': BOOL},
}
SEND_RESULT = {'type': 'object', 'required': ['message', 'replies'],
               'properties': {'message': MESSAGE, 'replies': {'type': 'array', 'items': MESSAGE}, 'replayed': BOOL}}

CALENDAR = {'type': 'object', 'required': ['month', 'events'],
            'properties': {'month': STR, 'events': {'type': 'array', 'items': {
                'type': 'object', 'required': ['date', 'level', 'label'],
                'properties': {'date': DATE, 'level': {'type': 'string', 'enum': ['major', 'minor']}, 'label': STR}}}}}

SCHEDULE_ITEM = {'type': 'object', 'required': ['time', 'type', 'title', 'shipmentId', 'party', 'status'],
                 'properties': {'time': STR, 'type': {'type': 'string', 'enum': ['packed', 'customs', 'in_transit', 'delivered', 'deadline', 'alert', 'review']},
                                'title': STR, 'shipmentId': STR, 'party': STR, 'status': STR}}
SCHEDULE = {'type': 'object', 'required': ['date', 'items'], 'properties': {'date': DATE, 'items': {'type': 'array', 'items': SCHEDULE_ITEM}}}

INSIGHT = {'type': 'object', 'required': ['date', 'risk', 'summary', 'recommendations', 'source', 'available'],
           'properties': {'date': DATE, 'risk': {'type': 'string', 'enum': ['critical', 'high', 'medium', 'low']},
                          'summary': STR, 'recommendations': {'type': 'array', 'items': STR},
                          'source': {'type': 'object', 'required': ['provider', 'kind', 'label']},
                          'available': BOOL}}

TRACKING_MILESTONE = {'type': 'object', 'required': ['key', 'label', 'at', 'state'],
                      'properties': {'key': STR, 'label': STR, 'at': STR_OR_NULL,
                                     'state': {'type': 'string', 'enum': ['completed', 'current', 'upcoming']}}}
LATLNG = {'type': 'object', 'required': ['lat', 'lng'], 'properties': {'lat': NUM, 'lng': NUM}}
TRACKING = {
    **SHIPMENT,
    'required': SHIPMENT['required'] + ['synthetic', 'progress', 'stage', 'statusLabel', 'currentLocation', 'coords', 'eta',
                                        'temperatureC', 'tempRange', 'updatedAt', 'note', 'milestones', 'telemetry'],
    'properties': {**SHIPMENT['properties'], 'synthetic': BOOL, 'progress': NUM, 'stage': STR, 'statusLabel': STR,
                   'currentLocation': STR, 'coords': {'type': 'object', 'required': ['origin', 'current', 'destination'],
                                                      'properties': {'origin': LATLNG, 'current': LATLNG, 'destination': LATLNG}},
                   'eta': DATE_OR_NULL, 'temperatureC': {'type': ['number', 'null']}, 'tempRange': STR, 'updatedAt': DATETIME,
                   'note': STR, 'milestones': {'type': 'array', 'items': TRACKING_MILESTONE}, 'telemetry': STR},
}

INVENTORY = {'type': 'object', 'required': ['configured', 'live', 'items', 'message', 'provenance', 'sourceSystem'],
             'properties': {'configured': BOOL, 'live': BOOL, 'items': {'type': 'array'}, 'message': STR,
                            'provenance': STR, 'sourceSystem': STR_OR_NULL}}

PROPOSAL = {
    'type': 'object',
    'required': ['id', 'status', 'parentPlanId', 'eventId', 'warningId', 'option', 'createdAt', 'stale', 'comparison', 'contentHash'],
    'properties': {'id': STR, 'status': PLAN_STATUS, 'parentPlanId': STR_OR_NULL, 'eventId': STR_OR_NULL, 'warningId': STR_OR_NULL,
                   'option': {'type': ['object', 'null']}, 'createdAt': DATETIME, 'stale': BOOL, 'comparison': {'type': 'object'},
                   'contentHash': STR, 'decision': {'type': ['object', 'null']}},
}
CURRENT_PLAN = {'type': 'object', 'required': ['planId', 'version', 'approvedAt', 'approvedBy', 'status', 'appliedEventIds'],
                'properties': {'planId': STR, 'version': INT, 'approvedAt': STR_OR_NULL, 'approvedBy': STR_OR_NULL,
                               'status': PLAN_STATUS, 'appliedEventIds': {'type': 'array', 'items': STR}}}
DECISION_RESULT = {'type': 'object', 'required': ['proposalId', 'status', 'beforePlanId', 'afterPlanId', 'currentPlanId', 'currentPlanVersion', 'replayed'],
                   'properties': {'proposalId': STR, 'status': {'type': 'string', 'enum': ['approved', 'rejected']},
                                  'beforePlanId': STR_OR_NULL, 'afterPlanId': STR_OR_NULL, 'currentPlanId': STR,
                                  'currentPlanVersion': INT, 'replayed': BOOL}}
AUDIT_ENTRY = {'type': 'object', 'required': ['id', 'action', 'entityId', 'actor', 'createdAt', 'payload'],
               'properties': {'id': STR, 'action': STR, 'entityId': STR_OR_NULL, 'actor': STR, 'createdAt': DATETIME, 'payload': {'type': 'object'}}}
CONTEXT = {'type': 'object', 'required': ['today', 'trial', 'currentPlan', 'providers'],
           'properties': {'today': DATE, 'trial': {'type': 'object'}, 'currentPlan': CURRENT_PLAN, 'providers': {'type': 'object'}}}


def list_of(schema):
    return {'type': 'array', 'items': schema}


_TYPES = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'object': dict, 'array': list, 'null': type(None)}


def _is_type(value, name):
    if name in ('integer', 'number') and isinstance(value, bool):
        return False
    if name == 'integer' and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, _TYPES[name])


def validate(value, schema, path='$'):
    """Return a list of human-readable contract violations (empty when valid)."""
    errors = []
    types = schema.get('type')
    if types:
        names = types if isinstance(types, list) else [types]
        if not any(_is_type(value, name) for name in names):
            return [f'{path}: expected {"/".join(names)}, got {type(value).__name__}']
    if value is None:
        return errors
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: {value!r} not in {schema["enum"]}')
    if schema.get('pattern') == 'date' and isinstance(value, str):
        from datetime import date
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f'{path}: {value!r} is not an ISO date')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path}.{key}: required')
        for key, sub in schema.get('properties', {}).items():
            if key in value:
                errors.extend(validate(value[key], sub, f'{path}.{key}'))
    if isinstance(value, list) and 'items' in schema:
        for index, item in enumerate(value):
            errors.extend(validate(item, schema['items'], f'{path}[{index}]'))
    return errors


class ContractError(Exception):
    def __init__(self, endpoint, errors):
        super().__init__(f'{endpoint} violated its response contract: ' + '; '.join(errors[:5]))
        self.errors = errors


def check(endpoint, value, schema):
    errors = validate(value, schema)
    if errors:
        raise ContractError(endpoint, errors)
    return value
