from curl_cffi import requests as curl_requests

URLS = [
    "https://www.psx-place.com/",
    "https://www.psx-place.com/ewr-porta/page-2",
]

PROFILES = ["safari15_5", "safari17_0", "chrome124"]

HEADERS = {
    "safari-macos": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.psx-place.com/",
    },
    "chrome-windows": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.psx-place.com/",
    },
}

print("=== PSX-PLACE ACCESS PROBE START ===", flush=True)

success = False

for url in URLS:
    print(f"\nURL: {url}", flush=True)
    for profile in PROFILES:
        for header_name, headers in HEADERS.items():
            try:
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    headers=headers,
                    timeout=30,
                )
                html = response.text or ""
                ok = response.status_code == 200 and "/threads/" in html
                print(
                    f"profile={profile} headers={header_name} "
                    f"status={response.status_code} size={len(html)} ok={ok}",
                    flush=True,
                )
                if ok:
                    success = True
            except Exception as e:
                print(
                    f"profile={profile} headers={header_name} "
                    f"error={type(e).__name__}: {e}",
                    flush=True,
                )

print("\n=== PSX-PLACE ACCESS PROBE END ===", flush=True)

if success:
    print("At least one method can access PSX-Place.", flush=True)
else:
    print("No method could access PSX-Place from this runner.", flush=True)
