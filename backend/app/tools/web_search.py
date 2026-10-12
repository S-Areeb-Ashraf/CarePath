"""Serper web search client. Used for insurance/policy questions where live,
source-cited answers matter. API key and result count come from settings —
nothing is hardcoded."""
import httpx
from ..config import Settings
from ..schemas import ToolResult


class SerperSearch:
    def __init__(self, settings: Settings):
        self.settings = settings

    def search(self, query: str, num_results: int | None = None) -> ToolResult:
        if not self.settings.serper_api_key:
            return ToolResult(status='failed', tool_name='search_clinic_info', error_code='SEARCH_NOT_CONFIGURED', message='Web search is not configured (SERPER_API_KEY missing).')
        limit = num_results or self.settings.web_search_num_results
        payload = {'q': query, 'num': max(1, min(limit, 10))}
        try:
            response = httpx.post(
                'https://google.serper.dev/search',
                headers={'X-API-KEY': self.settings.serper_api_key, 'Content-Type': 'application/json'},
                json=payload,
                timeout=self.settings.tool_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            return ToolResult(status='failed', tool_name='search_clinic_info', error_code='SEARCH_PROVIDER_ERROR', message=f'Search provider returned HTTP {exc.response.status_code}.')
        except httpx.HTTPError as exc:
            return ToolResult(status='failed', tool_name='search_clinic_info', error_code='SEARCH_NETWORK_ERROR', message=f'Search request failed: {exc}')
        results = [
            {'title': item.get('title', ''), 'link': item.get('link', ''), 'snippet': item.get('snippet', '')}
            for item in (data.get('organic') or [])[:limit]
            if item.get('link')
        ]
        answer_box = data.get('answerBox') or {}
        if answer_box.get('snippet'):
            results.insert(0, {'title': answer_box.get('title', 'Answer box'), 'link': answer_box.get('link', ''), 'snippet': answer_box.get('snippet', '')})
        return ToolResult(status='confirmed', tool_name='search_clinic_info', data={'results': results})
