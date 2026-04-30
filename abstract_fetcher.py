"""通过 DOI 从 CrossRef API 获取文章摘要。"""

import os
import re
import time
import urllib.parse
import urllib.request
import json

CROSSREF_API = "https://api.crossref.org/works/"

_JATS_TAG_RE = re.compile(r"<[^>]+>")

_last_request_time = 0.0
_MIN_INTERVAL = 1.0


def _strip_jats(text):
    """剥离 JATS/HTML 标签，返回纯文本。"""
    return _JATS_TAG_RE.sub("", text).strip()


def _throttle():
    """简易限流：确保两次请求间隔 >= 1 秒。"""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def fetch_abstract_by_doi(doi):
    """通过 CrossRef API 查询 DOI 对应的摘要。

    返回纯文本摘要字符串，查询失败或无摘要时返回 None。
    """
    if not doi:
        return None

    encoded_doi = urllib.parse.quote(doi, safe="")
    url = f"{CROSSREF_API}{encoded_doi}"

    mailto = os.environ.get("CROSSREF_MAILTO", "")
    if mailto:
        url += f"?mailto={urllib.parse.quote(mailto)}"

    headers = {
        "User-Agent": f"AIMorningPost/1.0 (mailto:{mailto})" if mailto else "AIMorningPost/1.0",
        "Accept": "application/json",
    }

    _throttle()

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    [CrossRef] DOI {doi} 查询失败: {e}")
        return None

    abstract = data.get("message", {}).get("abstract", "")
    if not abstract:
        return None

    return _strip_jats(abstract)
