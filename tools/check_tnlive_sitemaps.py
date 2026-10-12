"""One-shot public HTTP diagnostics; never invoke the collector or its secrets.

No proxies, challenge solving, disguised search crawlers, private CMS endpoints
or alternative IPs. Use only the public publisher sitemap addresses.
"""

import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from src.config import USER_AGENT


BASE = "https://tnlive.sk"
NEWS = BASE + "/xml/sitemap-news.xml"
ARTICLES = BASE + "/xml/articles-current-sitemap.xml"
NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "sk,cs;q=0.8,en;q=0.5",
}


def describe_content(content, status):
    """Report structure/counts only, never dump articles or challenge HTML."""
    if status != 200:
        return {"usable": False, "reason": f"HTTP {status}"}
    if len(content) > 2_000_000:
        return {"usable": False, "reason": "response too large"}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"usable": False, "reason": "not sitemap XML"}
    root_name = root.tag.rsplit("}", 1)[-1]
    if root.tag not in (f"{{{NS['sm']}}}urlset", f"{{{NS['sm']}}}sitemapindex"):
        return {"usable": False, "reason": "unexpected XML root"}
    entries = root.findall("sm:url", NS)
    urls = sum(bool(e.findtext("sm:loc", namespaces=NS)) for e in entries)
    return {
        "usable": root_name == "urlset" and urls > 0,
        "root": root_name,
        "urls": urls,
        "child_sitemaps": len(root.findall("sm:sitemap", NS)),
        "titles": sum(bool(e.findtext("news:news/news:title", namespaces=NS)) for e in entries),
        "publication_dates": sum(bool(e.findtext("news:news/news:publication_date", namespaces=NS)) for e in entries),
        "date_only_lastmod": sum(
            len((e.findtext("sm:lastmod", namespaces=NS) or "").strip()) == 10
            for e in entries
        ),
    }


def request_probe(client, url, mode, headers=HEADERS):
    start = time.monotonic()
    result = {"mode": mode, "url": url}
    try:
        response = client.get(url, headers=headers, timeout=(5, 15))
        result.update({
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("Content-Type"),
            "cf_mitigated": response.headers.get("cf-mitigated"),
            "redirects": [r.status_code for r in response.history],
            **describe_content(response.content, response.status_code),
        })
    except requests.RequestException as exc:
        result.update({"usable": False, "error": type(exc).__name__})
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


def curl_probe(url):
    start = time.monotonic()
    result = {"mode": "standard curl", "url": url}
    marker = b"\n__TN_PROBE__"
    try:
        response = subprocess.run([
            "curl", "--silent", "--show-error", "--location", "--compressed",
            "--max-time", "20", "--write-out",
            "\n__TN_PROBE__%{http_code}|%{url_effective}|%{content_type}", url,
        ], capture_output=True, timeout=25, check=False)
        if response.returncode:
            result.update({"usable": False, "error": f"curl exit {response.returncode}"})
        else:
            body, metadata = response.stdout.rsplit(marker, 1)
            status, final_url, content_type = metadata.decode("utf-8", "replace").split("|", 2)
            result.update({"status": int(status), "final_url": final_url,
                           "content_type": content_type, **describe_content(body, int(status))})
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        result.update({"usable": False, "error": type(exc).__name__})
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


def report(results):
    lines = [
        "## TN Live: jednorazová diagnostika sitemap",
        "Bez AI, Discordu, produkčného stavu a obchádzania ochrany webu.",
        "",
        "| Dopyt | Adresa | HTTP | Použiteľné XML | URL | Titulky | Časy publikovania |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        lines.append(
            f"| {item['mode']} | {item['url']} | {item.get('status', 'error')} | "
            f"{'áno' if item.get('usable') else 'nie'} | {item.get('urls', 0)} | "
            f"{item.get('titles', 0)} | {item.get('publication_dates', 0)} |"
        )
    lines += ["", "Článková sitemapa potrebuje doplniť titulky a skutočný čas publikovania;",
              "lastmod označuje zmenu, nie nevyhnutne publikovanie. HTTP 200 bez platného",
              "XML a článkov nie je úspešný zber."]
    return "\n".join(lines) + "\n"


def main():
    results = []

    def emit(result):
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    for url in (BASE + "/robots.txt", BASE + "/sitemap.xml", NEWS, ARTICLES):
        emit(request_probe(requests, url, "project requests"))
    with requests.Session() as session:
        emit(request_probe(session, BASE + "/", "session: homepage"))
        for url in (NEWS, ARTICLES):
            emit(request_probe(session, url, "session: sitemap"))
    emit(request_probe(requests, NEWS, "identified agent", {
        "User-Agent": "sk-news-agent/1.0", "Accept": "application/xml",
    }))
    for url in (NEWS, ARTICLES):
        emit(curl_probe(url))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(report(results))
    return 0 if any(r.get("usable") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
