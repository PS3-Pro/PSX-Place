from curl_cffi import requests

URL = "https://www.psx-place.com/"
METHODS = [
    ("safari15_5", {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": URL,
    }),
    ("safari17_0", {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": URL,
    }),
    ("chrome124", {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": URL,
    }),
]

print("=== PSX-Place access probe ===", flush=True)
worked = False
for profile, headers in METHODS:
    try:
        r = requests.get(URL, impersonate=profile, headers=headers, timeout=30)
        text = r.text or ""
        ok = r.status_code == 200 and ("/threads/" in text or "Featured content" in text)
        print(f"profile={profile} status={r.status_code} size={len(text)} ok={ok}", flush=True)
        worked = worked or ok
    except Exception as e:
        print(f"profile={profile} error={type(e).__name__}: {e}", flush=True)
print("=== Probe finished ===", flush=True)
if not worked:
    print("WARNING: probe did not confirm a working method, scraper will still try all methods.", flush=True)
