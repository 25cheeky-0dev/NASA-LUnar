"""Bounded Gemini input extraction; never a source of scientific measurements."""
import os
import re
import ssl

import httpx
import truststore


def configured():
    return bool(os.getenv('GEMINI_API_KEY') and os.getenv('GEMINI_MODEL'))


async def extract(text, schema, instruction):
    model = os.environ['GEMINI_MODEL']
    if not re.fullmatch(r'[a-zA-Z0-9._-]+', model):
        raise ValueError('Invalid Gemini model identifier')
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8),
                                 verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as client:
        response = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']},
            json={'systemInstruction': {'parts': [{'text': instruction}]},
                  'contents': [{'role': 'user', 'parts': [{'text': text}]}],
                  'generationConfig': {'temperature': 0, 'maxOutputTokens': 1600,
                                       'responseMimeType': 'application/json',
                                       'responseJsonSchema': schema}})
        response.raise_for_status()
        candidate = response.json()['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Gemini did not finish a complete response')
        return ''.join(p['text'] for p in candidate['content']['parts'] if 'text' in p and not p.get('thought'))
