from curl_cffi import requests as curl_requests
import requests as plain_requests

PSX_BASE = "https://www.psx-place.com/"
URLS = [
    "https://www.psx-place.com/",
    "https://www.psx-place.com/ewr-porta/page-2",
]

CURL_PROFILES = [
    "safari15_5",
    "safari17_0",
    "safari18_0",
    "chrome101",
    "chrome110",
    "chrome120",
    "chrome124",
    "chrome131",
    "edge101",
    "edge110",
]

HEADER_SETS = [
    {
        "name": "minimal",
        "headers": {
            "User-Agent": "Mozilla/5.0",
        },
    },
    {
        "name": "safari-macos",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": PSX_BASE,
        },
    },
    {
        "name": "chrome-windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": PSX_BASE,
        },
    },
]


def has_article_html(text):
    if not text:
        return False
    markers = ["/threads/", "Featured content", "PSX-Place", "p-title", "contentRow-title"]
    return any(marker in text for marker in markers)


def short_body(text):
    text = (text or "").replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:260]


def run_probe():
    print("=== PSX-PLACE ACCESS PROBE START ===", flush=True)
    success = False

    for url in URLS:
        print("", flush=True)
        print(f"URL: {url}", flush=True)

        for profile in CURL_PROFILES:
            for header_set in HEADER_SETS:
                try:
                    response = curl_requests.get(
                        url,
                        impersonate=profile,
                        headers=header_set["headers"],
                        timeout=30,
                    )
                    html = response.text or ""
                    ok = response.status_code == 200 and has_article_html(html)
                    print(
                        f"curl_cffi profile={profile} headers={header_set['name']} "
                        f"status={response.status_code} size={len(html)} ok={ok}",
                        flush=True,
                    )
                    if not ok and response.status_code in (403, 429):
                        print(f"  body preview: {short_body(html)}", flush=True)
                    if ok:
                        success = True
                except Exception as e:
                    print(
                        f"curl_cffi profile={profile} headers={header_set['name']} "
                        f"error={type(e).__name__}: {e}",
                        flush=True,
                    )

        for header_set in HEADER_SETS:
            try:
                response = plain_requests.get(
                    url,
                    headers=header_set["headers"],
                    timeout=30,
                )
                html = response.text or ""
                ok = response.status_code == 200 and has_article_html(html)
                print(
                    f"plain_requests headers={header_set['name']} "
                    f"status={response.status_code} size={len(html)} ok={ok}",
                    flush=True,
                )
                if not ok and response.status_code in (403, 429):
                    print(f"  body preview: {short_body(html)}", flush=True)
                if ok:
                    success = True
            except Exception as e:
                print(
                    f"plain_requests headers={header_set['name']} "
                    f"error={type(e).__name__}: {e}",
                    flush=True,
                )

    print("", flush=True)
    print("=== PSX-PLACE ACCESS PROBE END ===", flush=True)

    if success:
        print("Probe result: at least one method worked from this runner.", flush=True)
    else:
        print("Probe result: no method worked from this runner. This is likely an IP/network block.", flush=True)


if __name__ == "__main__":
    run_probe()
