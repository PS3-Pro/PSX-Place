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
    (
        "safari-macos",
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.psx-place.com/",
        },
    ),
    (
        "chrome-windows",
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.psx-place.com/",
        },
    ),
]


def looks_like_portal_html(text):
    if not text:
        return False
    low = text.lower()
    return "psx-place" in low and ("threads/" in low or "featured" in low or "porta" in low)


print("=== PSX-PLACE ACCESS PROBE START ===", flush=True)

any_success = False

for url in URLS:
    print(f"URL: {url}", flush=True)

    for profile in CURL_PROFILES:
        for header_name, headers in HEADER_SETS:
            try:
                r = curl_requests.get(url, impersonate=profile, headers=headers, timeout=30)
                ok = r.status_code == 200 and looks_like_portal_html(r.text or "")
                print(
                    f"curl_cffi profile={profile} headers={header_name} "
                    f"status={r.status_code} size={len(r.text or '')} ok={ok}",
                    flush=True,
                )
                any_success = any_success or ok
            except Exception as e:
                print(
                    f"curl_cffi profile={profile} headers={header_name} "
                    f"error={type(e).__name__}: {e}",
                    flush=True,
                )

    for header_name, headers in HEADER_SETS:
        try:
            r = plain_requests.get(url, headers=headers, timeout=30)
            ok = r.status_code == 200 and looks_like_portal_html(r.text or "")
            print(
                f"plain_requests headers={header_name} "
                f"status={r.status_code} size={len(r.text or '')} ok={ok}",
                flush=True,
            )
            any_success = any_success or ok
        except Exception as e:
            print(
                f"plain_requests headers={header_name} error={type(e).__name__}: {e}",
                flush=True,
            )

print("=== PSX-PLACE ACCESS PROBE END ===", flush=True)

if any_success:
    print("Probe result: at least one method can access PSX-Place.", flush=True)
else:
    print("Probe result: no tested method could access PSX-Place from this runner.", flush=True)
