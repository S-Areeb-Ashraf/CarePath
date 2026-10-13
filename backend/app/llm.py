import json
import re
import time
import httpx
from pydantic import BaseModel, Field
from .config import Settings

class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)

class IntentExtraction(BaseModel):
    intent: str
    patient_reference: str | None = None
    appointment_id: str | None = None
    slot_id: str | None = None
    specialty: str | None = None
    requested_date: str | None = None
    is_confirmation: bool = False
    confidence: float = 0

class ClarificationQuestion(BaseModel):
    question: str = Field(min_length=1)

class LLMUnavailable(RuntimeError):
    pass

class ToolCallRequest(BaseModel):
    id: str = ''
    name: str
    arguments: dict = {}
    thought_signature: str | None = None  # required by Gemini 3 when echoing tool calls back

class ChatTurn(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCallRequest] = []

class LLMClient:
    """OpenAI-compatible chat client. Provider URL and model are configuration, not source code."""
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _content_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get('text'):
                    parts.append(str(item['text']))
            return '\n'.join(parts)
        if isinstance(content, dict) and content.get('text'):
            return str(content['text'])
        return str(content)

    @classmethod
    def _json_object(cls, content: object) -> dict:
        text = cls._content_text(content).strip()
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find('{'), text.rfind('}')
            if start < 0 or end <= start:
                raise
            value = json.loads(text[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError('LLM JSON response was not an object')
        return value

    def grounded_answer(self, question: str, contexts: list[dict]) -> GroundedAnswer:
        if self.settings.llm_provider == 'stub':
            raise LLMUnavailable('LLM_PROVIDER is stub; configure a real provider for production.')
        if not self.settings.llm_base_url or not self.settings.llm_api_key:
            raise LLMUnavailable('LLM_BASE_URL and LLM_API_KEY are required for the configured provider.')
        context = '\n\n'.join(f"SOURCE_ID: {item['source']}\nTITLE: {item['title']}\nTEXT: {item['text']}" for item in contexts)
        payload = {'model':self.settings.llm_model_primary,'temperature':0,'response_format':{'type':'json_object'},'messages':[
            {'role':'system','content':'You answer patient-service questions only from the supplied sources. Return JSON with exactly answer (string) and citations (array of SOURCE_ID values). If the sources do not answer the question, return an answer saying you do not have confirmed information and cite the closest source.'},
            {'role':'user','content':f'Question:\n{question}\n\nTrusted sources:\n{context}'}]}
        try:
            response = httpx.post(f"{self.settings.llm_base_url.rstrip('/')}/chat/completions", headers={'Authorization':f'Bearer {self.settings.llm_api_key}'}, json=payload, timeout=self.settings.llm_timeout_seconds)
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            result = GroundedAnswer.model_validate(self._json_object(content))
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].replace(self.settings.llm_api_key, '[redacted]')
            raise LLMUnavailable(f'LLM provider returned HTTP {exc.response.status_code}: {detail}') from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable('The configured LLM did not return a valid grounded response.') from exc
        allowed = {item['source'] for item in contexts}
        if not set(result.citations).issubset(allowed):
            raise LLMUnavailable('The LLM cited a source that was not retrieved.')
        return result

    def extract_intent(self, message: str) -> IntentExtraction:
        if self.settings.llm_provider == 'stub' or not self.settings.llm_base_url or not self.settings.llm_api_key:
            raise LLMUnavailable('A real LLM provider is not configured.')
        payload = {'model':self.settings.llm_model_primary,'temperature':0,'response_format':{'type':'json_object'},'messages':[
            {'role':'system','content':'Extract patient-service intent only. Return JSON with intent, patient_reference, appointment_id, slot_id, specialty, requested_date, is_confirmation, confidence. requested_date must be YYYY-MM-DD only when explicitly known; never invent missing values. is_confirmation is true only when the user explicitly confirms the pending action. Allowed intents: booking, rescheduling, cancellation, availability, appointment_lookup, preparation, general_question, escalation, unknown.'},
            {'role':'user','content':message}]}
        try:
            response = httpx.post(f"{self.settings.llm_base_url.rstrip('/')}/chat/completions", headers={'Authorization':f'Bearer {self.settings.llm_api_key}'}, json=payload, timeout=self.settings.llm_timeout_seconds)
            response.raise_for_status()
            payload = self._json_object(response.json()['choices'][0]['message']['content'])
            if 'confidence' not in payload: payload['confidence'] = 0.8
            return IntentExtraction.model_validate(payload)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].replace(self.settings.llm_api_key, '[redacted]')
            raise LLMUnavailable(f'LLM provider returned HTTP {exc.response.status_code}: {detail}') from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable('The configured LLM did not return a valid intent object.') from exc

    def clarification_question(self, missing_field: str, known_fields: dict[str, object]) -> ClarificationQuestion:
        payload = {'model':self.settings.llm_model_primary,'temperature':0.2,'response_format':{'type':'json_object'},'messages':[
            {'role':'system','content':'You are a patient-service assistant. Ask exactly one concise clarification question. Ask only for the missing field. Do not claim that any appointment action has happened. Return JSON with exactly one key: question.'},
            {'role':'user','content':f'Missing field: {missing_field}\nKnown fields: {json.dumps(known_fields, default=str)}'}]}
        try:
            response = httpx.post(f"{self.settings.llm_base_url.rstrip('/')}/chat/completions", headers={'Authorization':f'Bearer {self.settings.llm_api_key}'}, json=payload, timeout=self.settings.llm_timeout_seconds)
            response.raise_for_status()
            return ClarificationQuestion.model_validate(self._json_object(response.json()['choices'][0]['message']['content']))
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].replace(self.settings.llm_api_key, '[redacted]')
            raise LLMUnavailable(f'LLM provider returned HTTP {exc.response.status_code}: {detail}') from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable('The configured LLM did not return a valid clarification question.') from exc

    def _require_provider(self) -> None:
        if self.settings.llm_provider == 'stub' or not self.settings.llm_base_url or not self.settings.llm_api_key:
            raise LLMUnavailable('A real LLM provider is not configured.')

    def chat_completion(self, messages: list[dict], tools: list[dict] | None = None, model: str | None = None, temperature: float = 0.1) -> ChatTurn:
        """Generic chat completion with optional function tools. Provider-agnostic:
        works with any OpenAI-compatible endpoint configured via LLM_BASE_URL."""
        self._require_provider()
        payload: dict = {'model': model or self.settings.llm_model_primary, 'temperature': temperature, 'messages': messages}
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        try:
            response = httpx.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={'Authorization': f'Bearer {self.settings.llm_api_key}'},
                json=payload,
                timeout=self.settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            message = response.json()['choices'][0]['message']
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].replace(self.settings.llm_api_key, '[redacted]')
            raise LLMUnavailable(f'LLM provider returned HTTP {exc.response.status_code}: {detail}') from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable('The configured LLM did not return a valid chat response.') from exc
        calls = []
        for raw in message.get('tool_calls') or []:
            function = raw.get('function') or {}
            name = function.get('name')
            if not name:
                continue
            raw_arguments = function.get('arguments') or '{}'
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            calls.append(ToolCallRequest(
                id=str(raw.get('id') or f'call_{len(calls)}_{int(time.time())}'),
                name=name,
                arguments=arguments,
                thought_signature=(
                    (raw.get('extra_content') or {}).get('google', {}).get('thought_signature')
                    or raw.get('thought_signature')
                    or (function.get('extra_content') or {}).get('google', {}).get('thought_signature')
                    or function.get('thought_signature')
                ),
            ))
        return ChatTurn(content=message.get('content'), tool_calls=calls)

    def check_connection(self) -> dict[str, object]:
        if self.settings.llm_provider == 'stub' or not self.settings.llm_base_url or not self.settings.llm_api_key:
            return {'ok':False,'status':'not_configured','detail':'Configure LLM_PROVIDER, LLM_BASE_URL, and LLM_API_KEY.'}
        try:
            response = httpx.get(f"{self.settings.llm_base_url.rstrip('/')}/models", headers={'Authorization':f'Bearer {self.settings.llm_api_key}'}, timeout=self.settings.llm_timeout_seconds)
            response.raise_for_status()
            models = [item.get('id') for item in response.json().get('data', [])]
            return {'ok':True,'status':'connected','configured_primary':self.settings.llm_model_primary,'configured_secondary':self.settings.llm_model_secondary,'available_models':models[:50]}
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].replace(self.settings.llm_api_key, '[redacted]')
            return {'ok':False,'status':'provider_error','http_status':exc.response.status_code,'detail':detail}
        except httpx.HTTPError as exc:
            return {'ok':False,'status':'network_error','detail':str(exc)}
