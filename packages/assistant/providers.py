"""Optional OpenAI-backed, read-only assistant with deterministic local fallback."""
import json
import os
from urllib.request import Request, urlopen

from .grounded import answer_question


class LocalAssistantProvider:
    name = 'local'

    def answer(self, question, scenario, dataset, comparison=None):
        return {**answer_question(question, scenario, dataset, comparison), 'provider':'local'}


class OpenAIAssistantProvider:
    name = 'openai'

    def __init__(self, api_key=None, model=None, base_url=None, timeout=None):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY','')
        self.model = model or os.getenv('OPENAI_MODEL','gpt-5.4-mini')
        self.base_url = (base_url or os.getenv('OPENAI_API_BASE','https://api.openai.com/v1')).rstrip('/')
        self.timeout = float(timeout or os.getenv('OPENAI_TIMEOUT_SECONDS','20'))

    def _post(self, payload):
        request = Request(self.base_url + '/responses', data=json.dumps(payload).encode(), headers={
            'Authorization':'Bearer ' + self.api_key, 'Content-Type':'application/json'
        }, method='POST')
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    @staticmethod
    def _text(response):
        return ''.join(part.get('text','') for item in response.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text')

    def answer(self, question, scenario, dataset, comparison=None):
        local = answer_question(question, scenario, dataset, comparison)
        if not self.api_key:
            return {**local,'provider':'local','fallback_reason':'OPENAI_API_KEY is not configured'}
        if 'cannot approve' in local['answer']:
            return {**local,'provider':'local'}
        context = {
            'scenario':{k:scenario.get(k) for k in ('id','name','status','as_of','metrics','shipments','repair_options','assumptions')},
            'comparison':comparison,
            'evidence':local['citations'],
        }
        tool = {'type':'function','name':'get_planning_context','description':'Read the selected immutable planning scenario, shipment calculations, comparison, and cited evidence. This tool cannot modify or approve anything.','strict':True,'parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False}}
        instructions = ('Answer only from get_planning_context. Clearly distinguish verified, needs-review, and synthetic evidence. '
                        'Never approve, reject, modify, or claim legal advice. Return concise plain text and refer to sources by title.')
        try:
            first = self._post({'model':self.model,'instructions':instructions,'input':str(question)[:4000],'tools':[tool],'tool_choice':{'type':'function','name':'get_planning_context'},'store':False})
            calls = [item for item in first.get('output',[]) if item.get('type')=='function_call' and item.get('name')=='get_planning_context']
            if not calls:
                raise ValueError('Model did not request the planning context')
            outputs = [{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(context,ensure_ascii=False)[:120000]} for call in calls]
            final = self._post({'model':self.model,'instructions':instructions,'previous_response_id':first['id'],'input':outputs,'store':False})
            text = self._text(final).strip()
            if not text:
                raise ValueError('Model returned no answer')
            return {**local,'answer':text + '\n\nDecision support only; this answer cannot approve changes or provide regulatory or legal advice.','provider':'openai','model':self.model,'tools_used':['get_planning_context']}
        except Exception as exc:
            return {**local,'provider':'local','fallback_reason':type(exc).__name__}


def configured_assistant():
    if os.getenv('ASSISTANT_PROVIDER','local').lower() == 'openai':
        return OpenAIAssistantProvider()
    return LocalAssistantProvider()
