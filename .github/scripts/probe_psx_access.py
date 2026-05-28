from curl_cffi import requests as curl_requests
import requests as plain_requests

URLS = [
    "https://www.psx-place.com/",
    "https://www.psx-place.com/ewr-porta/page-2",
]

CURL_PROFILES = [
    "safari15_5",
    "safari17_0",
    "chrome120",
    "chrome124",
    "chrome131",
]

HEADER_SETS = [
    {
        "name": "safari-macos",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.psx-place.com/",
        },
    },
    {
        "name": "chrome-windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.psx-place.com/",
        },
    },
]


def looks_ok(text):
    return bool(text) and ("/threads/" in text or "Featured content" in text or "PSX-Place" in text)


print("=== PSX-PLACE ACCESS PROBE START ===", flush=True)
worked = False
for url in URLS:
    print(f"URL: {url}", flush=True)
    for profile in CURL_PROFILES:
        for header_set in HEADER_SETS:
            try:
                r = curl_requests.get(url, impersonate=profile, headers=header_set["headers"], timeout=30)
                ok = r.status_code == 200 and looks_ok(r.text)
                print(f"curl_cffi profile={profile} headers={header_set['name']} status={r.status_code} size={len(r.text or '')} ok={ok}", flush=True)
                worked = worked or ok
            except Exception as e:
                print(f"curl_cffi profile={profile} headers={header_set['name']} error={type(e).__name__}: {e}", flush=True)
    for header_set in HEADER_SETS:
        try:
            r = plain_requests.get(url, headers=header_set["headers"], timeout=30)
            ok = r.status_code == 200 and looks_ok(r.text)
            print(f"plain_requests headers={header_set['name']} status={r.status_code} size={len(r.text or '')} ok={ok}", flush=True)
            worked = worked or ok
        except Exception as e:
            print(f"plain_requests headers={header_set['name']} error={type(e).__name__}: {e}", flush=True)
print("=== PSX-PLACE ACCESS PROBE END ===", flush=True)
if worked:
    print("At least one access method worked.", flush=True)
else:
    print("WARNING: No probe method worked. The scraper will still try its fallback list.", flush=True)
