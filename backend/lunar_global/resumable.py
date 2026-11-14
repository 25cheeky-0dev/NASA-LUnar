"""Bounded HTTPS downloads with ETag-bound resume and verified local receipts."""
import hashlib
import json
import os
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
import httpx
import truststore


def download(url, directory, maximum_bytes=64*1024*1024):
    from .sources import OFFICIAL_HOSTS
    from .storage import sha256
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in OFFICIAL_HOSTS or parsed.query or parsed.fragment:
        raise ValueError('Source download requires approved official HTTPS archive')
    target=Path(directory)/Path(parsed.path).name
    target.parent.mkdir(parents=True,exist_ok=True)
    receipt=target.with_suffix(target.suffix+'.receipt.json')
    partial=target.with_suffix(target.suffix+'.partial')
    state=partial.with_suffix(partial.suffix+'.json')
    lock=target.with_suffix(target.suffix+'.lock')
    if target.exists():
        evidence=json.loads(receipt.read_text())
        if evidence['url']!=url or sha256(target)!=evidence['sha256']:
            raise ValueError('Cached source checksum mismatch')
        return target,evidence
    # Prevent concurrent writers, never delete another job's lock.
    with lock.open('x') as guard:
        guard.write(str(os.getpid()))
    try:
        with httpx.Client(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                          timeout=httpx.Timeout(45,connect=10),follow_redirects=False) as client:
            for attempt in range(3):
                offset=0; etag=None
                if partial.exists() and state.exists():
                    prior=json.loads(state.read_text())
                    if prior.get('url')!=url:
                        raise ValueError('Partial source URL mismatch')
                    etag=prior.get('etag')
                    if etag and not etag.startswith('W/'):
                        offset=partial.stat().st_size
                headers={'Accept-Encoding':'identity'}
                if offset:
                    headers.update(Range=f'bytes={offset}-',**{'If-Range':etag})
                try:
                    with client.stream('GET',url,headers=headers) as response:
                        response.raise_for_status()
                        resume=response.status_code==206 and offset>0
                        if response.status_code not in (200,206):
                            raise ValueError('Unexpected scientific download response')
                        if resume and (response.headers.get('etag')!=etag or not response.headers.get('content-range','').startswith(f'bytes {offset}-')):
                            raise ValueError('Resume response identity/range mismatch')
                        if response.status_code==206 and not resume:
                            raise ValueError('Unexpected partial response')
                        count=offset if resume else 0
                        length=int(response.headers.get('content-length','0'))
                        if count+length>maximum_bytes:
                            raise ValueError('Source download exceeds byte budget')
                        state.write_text(json.dumps({'url':url,'etag':response.headers.get('etag')}))
                        with partial.open('ab' if resume else 'wb') as stream:
                            for chunk in response.iter_bytes():
                                count+=len(chunk)
                                if count>maximum_bytes:
                                    raise ValueError('Source download exceeds byte budget')
                                stream.write(chunk)
                        if length and partial.stat().st_size != (offset if resume else 0)+length:
                            raise ValueError('Incomplete source length')
                    evidence={'url':url,'sha256':sha256(partial),'bytes':count,
                              'downloaded_utc':datetime.now(UTC).isoformat(),
                              'authentication':'TLS official archive; locally computed SHA256, not publisher signature'}
                    # Receipt first; a crash leaves a recoverable partial, not an
                    # apparently completed unverified target.
                    temp_receipt=receipt.with_suffix(receipt.suffix+'.tmp')
                    temp_receipt.write_text(json.dumps(evidence,indent=2))
                    os.replace(temp_receipt,receipt);os.replace(partial,target)
                    state.unlink(missing_ok=True)
                    return target,evidence
                except (httpx.TransportError,httpx.HTTPStatusError) as exc:
                    if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code not in (429,500,502,503,504):
                        raise
                    if attempt==2:raise
                    time.sleep(2**attempt)
    finally:
        lock.unlink(missing_ok=True)
