import requests
from retry import retry
from requests.exceptions import RequestException

from .config import ddcheck_config

OPENAI_URL = ddcheck_config.openai_base_url
OPENAI_KEY = ddcheck_config.openai_api_key

def openai_completion(
    prompt, system_message=None, temperature=0.3, model="gpt-4o-mini", json_output=False
) -> str:
    if system_message:
        message = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]
    else:
        message = [{"role": "user", "content": prompt}]
    data = {
        "model": model,
        "temperature": temperature,
        "messages": message,
        "stream": False,
        "response_format": {"type": "json_object"} if json_output else None,
    }
    res = call_api(OPENAI_URL, OPENAI_KEY, data)
    answer = res["choices"][0]["message"]["content"]

    return answer


@retry(exceptions=RequestException, tries=5, delay=2, backoff=2, jitter=(1, 3))
def call_api(url, access_token, data):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()
