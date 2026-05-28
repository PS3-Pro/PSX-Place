import hashlib
import os
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
import requests as plain_requests
from PIL import Image, ImageOps


PSX_BASE = "https://www.psx-place.com/"
GITHUB_RAW_PREFIX = "https://raw.githubusercontent.com/PS3-Pro/PSX-Place/master/resources/images/uncompressed/"

MAX_PAGES = int(os.environ.get("PSX_MAX_PAGES", "20"))
MAX_ITEMS = int(os.environ.get("PSX_MAX_ITEMS", "120"))
REQUEST_DELAY = float(os.environ.get("PSX_REQUEST_DELAY", "1.0"))
DETAIL_DELAY = float(os.environ.get("PSX_DETAIL_DELAY", "0.35"))
FORCE_IMAGE_REFRESH = os.environ.get("PSX_FORCE_IMAGE_REFRESH", "0") == "1"

DIR_FILES = "files"
DIR_UNCOMPRESSED = os.path.join("resources", "images", "uncompressed")
DIR_COMPRESSED = os.path.join("resources", "images", "compressed")
XML_PATH = os.path.join(DIR_FILES, "whats_new.xml")

CURL_PROFILES = [
    os.environ.get("PSX_IMPERSONATE", "safari15_5"),
    "safari17_0",
    "safari18_0",
    "chrome124",
    "chrome131",
    "chrome120",
    "chrome110",
    "edge110",
]

HEADER_SETS = [
    {
        "name": "safari-macos",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    },
    {
        "name": "chrome-windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    },
    {
        "name": "minimal",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": PSX_BASE,
        },
    },
]


def now_stamp():
    return datetime.now().strftime("%H:%M:%S")


def log(message):
    print(f"[{now_stamp()}] {message}", flush=True)


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def xml_escape(text):
    return escape(str(text or ""), {'"': "&quot;", "'": "&apos;"})


def normalize_url(href, base=PSX_BASE):
    if not href:
        return ""
    url = urljoin(base, href).split("#")[0]
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def canonical_thread_url(url):
    """Keep portal/thread links stable and avoid duplicated post/page URLs."""
    url = normalize_url(url)
    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path

    # Convert /threads/title.12345/post-999999 to /threads/title.12345/
    path = re.sub(r"/post-\d+/?$", "/", path)

    # Convert /threads/title.12345/page-2 to /threads/title.12345/
    path = re.sub(r"/page-\d+/?$", "/", path)

    # Normalize final slash for XenForo thread URLs.
    if re.search(r"\.\d+/?$", path) and not path.endswith("/"):
        path += "/"

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def portal_url(page):
    if page <= 1:
        return PSX_BASE
    return f"{PSX_BASE}ewr-porta/page-{page}"


def has_article_html(text):
    if not text:
        return False
    markers = ["/threads/", "Featured content", "contentRow-title", "p-title", "bbWrapper"]
    return any(marker in text for marker in markers)


def short_body(text):
    text = (text or "").replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())[:260]


def fetch_html(url, timeout=30):
    for profile in dict.fromkeys(CURL_PROFILES):
        for header_set in HEADER_SETS:
            try:
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    timeout=timeout,
                    headers=header_set["headers"],
                )
                html = response.text or ""
                ok = response.status_code == 200 and html
                log(
                    f"GET {url} -> curl_cffi profile={profile} headers={header_set['name']} "
                    f"HTTP {response.status_code}, {len(html)} chars"
                )
                if ok:
                    return html
                if response.status_code in (403, 429):
                    log(f"Blocked response preview: {short_body(html)}")
            except Exception as e:
                log(f"curl_cffi error profile={profile} headers={header_set['name']}: {type(e).__name__}: {e}")

    for header_set in HEADER_SETS:
        try:
            response = plain_requests.get(url, headers=header_set["headers"], timeout=timeout)
            html = response.text or ""
            ok = response.status_code == 200 and html
            log(f"GET {url} -> plain_requests headers={header_set['name']} HTTP {response.status_code}, {len(html)} chars")
            if ok:
                return html
            if response.status_code in (403, 429):
                log(f"Blocked response preview: {short_body(html)}")
        except Exception as e:
            log(f"plain_requests error headers={header_set['name']}: {type(e).__name__}: {e}")

    log(f"Giving up after all methods: {url}")
    return ""


def is_article_url(url):
    return "/threads/" in url


def is_bad_title(text):
    if not text:
        return True
    title = clean_text(text)
    low = title.lower()
    bad_exact = {
        "next", "prev", "previous", "first", "last", "go", "here", "click here",
        "read more", "continue", "like", "quote", "reply", "share",
    }
    if low in bad_exact:
        return True
    if len(title) < 15:
        return True
    if low.startswith("image:"):
        return True
    if "comments:" in low or "replies:" in low:
        return True
    if re.fullmatch(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{1,2}(,\s*\d{4})?", low):
        return True
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", low):
        return True
    return False


def extract_portal_links(soup):
    selectors = [
        "h1 a[href*='/threads/']",
        "h2 a[href*='/threads/']",
        "h3 a[href*='/threads/']",
        ".contentRow-title a[href*='/threads/']",
        ".porta-title a[href*='/threads/']",
        ".message-title a[href*='/threads/']",
        ".structItem-title a[href*='/threads/']",
    ]
    found = []
    for selector in selectors:
        for a in soup.select(selector):
            href = canonical_thread_url(a.get("href"))
            title = clean_text(a.get("title") or a.get_text(" ", strip=True))
            if is_article_url(href) and not is_bad_title(title):
                found.append({"title": title, "link": href})

    if len(found) < 3:
        # Last-resort fallback. Avoid links embedded in article text such as
        # related posts or inline references, because those create duplicated/non-news items.
        for a in soup.select("a[href*='/threads/']"):
            href = canonical_thread_url(a.get("href"))
            title = clean_text(a.get("title") or a.get_text(" ", strip=True))

            parent_classes = " ".join(" ".join(p.get("class", [])) for p in a.parents if getattr(p, "get", None))
            likely_title_area = any(token in parent_classes for token in [
                "contentRow-title",
                "porta-title",
                "structItem-title",
                "message-title",
                "block-header",
                "p-title",
                "articlePreview-title",
            ])

            if not likely_title_area:
                continue

            if is_article_url(href) and not is_bad_title(title):
                found.append({"title": title, "link": href})

    unique = []
    seen = set()
    for item in found:
        if item["link"] in seen:
            continue
        seen.add(item["link"])
        unique.append(item)
    return unique


def get_meta_content(soup, *keys):
    for key in keys:
        tag = soup.select_one(f'meta[property="{key}"]') or soup.select_one(f'meta[name="{key}"]')
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))
    return ""


def parse_date_to_ps3(value):
    if not value:
        return "1970-01-01T00:00:00.000Z"
    try:
        value = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return f"{dt.year}-{dt.month}-{dt.day}T{dt.hour:02}:{dt.minute:02}:00.000Z"
    except Exception:
        return "1970-01-01T00:00:00.000Z"


def extract_thread_id(url):
    match = re.search(r"\.(\d+)/?$", url)
    if match:
        return match.group(1)
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def clean_title(title):
    title = clean_text(title)
    title = title.replace("(Forum Thread)", "").strip()
    return re.sub(r"\s*\|\s*PSX-Place\s*$", "", title).strip()


def safe_image_filename(title, link):
    thread_id = extract_thread_id(link)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", clean_title(title))
    safe = re.sub(r"_+", "_", safe).strip("._-")
    safe = safe[:80] or "psx_place"
    return f"{thread_id}_{safe}.jpg"


def is_good_image_url(url):
    if not url:
        return False
    low = url.lower()
    bad_parts = ["avatar", "avatars", "smilie", "smilies", "sprite", "logo", "like", "reaction", "styles/", "blank.gif", "data:image"]
    return not any(part in low for part in bad_parts)


def get_img_src(img, base_url):
    for attr in ("data-url", "data-src", "src"):
        src = img.get(attr)
        if src:
            return normalize_url(src, base_url)
    return ""


def extract_first_good_image(soup, base_url):
    meta_img = get_meta_content(soup, "og:image", "twitter:image")
    if is_good_image_url(meta_img):
        return normalize_url(meta_img, base_url)

    body = (
        soup.select_one(".message--article .bbWrapper")
        or soup.select_one(".message-body .bbWrapper")
        or soup.select_one("[itemprop='articleBody']")
        or soup.select_one(".bbWrapper")
        or soup
    )
    for img in body.select("img"):
        src = get_img_src(img, base_url)
        if is_good_image_url(src):
            return src
    return ""


def extract_summary(soup):
    body = (
        soup.select_one(".message--article .bbWrapper")
        or soup.select_one(".message-body .bbWrapper")
        or soup.select_one("[itemprop='articleBody']")
        or soup.select_one(".bbWrapper")
    )
    if body:
        for unwanted in body.select("script, style, blockquote, .bbCodeBlock"):
            unwanted.decompose()
        summary = clean_text(body.get_text(" ", strip=True))
        if summary:
            return summary[:900]
    meta_desc = get_meta_content(soup, "description", "og:description")
    return meta_desc[:900] if meta_desc else ""


def extract_author(soup):
    author = get_meta_content(soup, "author", "article:author")
    if author:
        return author
    selectors = ["a.username", ".message-name a", ".message-userDetails a.username", ".p-description a[href*='/members/']", "a[href*='/members/']"]
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            name = clean_text(tag.get_text(" ", strip=True))
            if name and len(name) <= 40:
                return name
    return "PSX-Place"


def extract_article_date(soup):
    date_value = get_meta_content(soup, "article:published_time", "article:modified_time", "og:updated_time")
    if date_value:
        return parse_date_to_ps3(date_value)
    time_tag = soup.select_one("time[datetime]")
    if time_tag and time_tag.get("datetime"):
        return parse_date_to_ps3(time_tag.get("datetime"))
    return "1970-01-01T00:00:00.000Z"


def read_article_detail(item):
    html = fetch_html(item["link"], timeout=30)
    if not html:
        log(f"Could not open article, using fallback data: {item['link']}")
        title = clean_title(item["title"])
        return {"title": title, "link": item["link"], "image_url": "", "image_name": "default.png", "author": "PSX-Place", "summary": title, "date": "1970-01-01T00:00:00.000Z"}

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("h1.p-title-value") or soup.select_one("h1")
    title = clean_title(title_tag.get_text(" ", strip=True) if title_tag else item["title"])
    if not title:
        title = clean_title(get_meta_content(soup, "og:title") or item["title"])

    return {
        "title": title,
        "link": item["link"],
        "image_url": extract_first_good_image(soup, item["link"]),
        "image_name": "default.png",
        "author": extract_author(soup),
        "summary": extract_summary(soup) or title,
        "date": extract_article_date(soup),
    }


def save_jpeg_versions(img, path_uncompressed, path_compressed):
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    img.save(path_uncompressed, "JPEG", quality=92, optimize=True)
    img_optimized = ImageOps.fit(img, (290, 170), Image.Resampling.LANCZOS)
    img_optimized.save(path_compressed, "JPEG", quality=80, optimize=True)


def download_and_process_image(image_url, image_name):
    path_uncompressed = os.path.join(DIR_UNCOMPRESSED, image_name)
    path_compressed = os.path.join(DIR_COMPRESSED, image_name)

    if not FORCE_IMAGE_REFRESH and os.path.exists(path_uncompressed) and os.path.exists(path_compressed):
        log(f"Image already exists, skipping: {image_name}")
        return True

    if not FORCE_IMAGE_REFRESH and os.path.exists(path_uncompressed) and not os.path.exists(path_compressed):
        try:
            log(f"Rebuilding compressed image from existing original: {image_name}")
            img = Image.open(path_uncompressed)
            save_jpeg_versions(img, path_uncompressed, path_compressed)
            return True
        except Exception as e:
            log(f"Could not rebuild compressed image, downloading again: {image_name} -> {e}")

    try:
        response = curl_requests.get(image_url, impersonate="safari15_5", timeout=20, headers=HEADER_SETS[0]["headers"])
        log(f"Image GET {image_url} -> HTTP {response.status_code}, {len(response.content or b'')} bytes")
        if response.status_code != 200 or not response.content:
            return False
        img = Image.open(BytesIO(response.content))
        save_jpeg_versions(img, path_uncompressed, path_compressed)
        log(f"Saved image: {image_name}")
        return True
    except Exception as e:
        log(f"Image error for {image_name}: {e}")
        return False


def collect_news():
    seeds = []
    seen_links = set()

    for current_page in range(1, MAX_PAGES + 1):
        url = portal_url(current_page)
        log(f"Scraping portal page {current_page}: {url}")
        html = fetch_html(url)
        if not html:
            log(f"Empty or failed portal page: {url}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        links = extract_portal_links(soup)
        log(f"Portal page {current_page}: found {len(links)} possible articles")

        if not links and current_page > 1:
            log("No more articles found, stopping pagination")
            break

        for item in links:
            if item["link"] in seen_links:
                continue
            seen_links.add(item["link"])
            seeds.append(item)
            if len(seeds) >= MAX_ITEMS:
                break
        if len(seeds) >= MAX_ITEMS:
            break
        time.sleep(REQUEST_DELAY)

    log(f"Reading article details: {len(seeds)} items")
    news_list = []
    for i, item in enumerate(seeds, 1):
        log(f"Article detail {i}/{len(seeds)}: {item['title'][:90]}")
        news_list.append(read_article_detail(item))
        time.sleep(DETAIL_DELAY)
    return news_list


def process_images(news_list):
    log(f"Processing images for {len(news_list)} articles")
    assigned = 0
    fallback = 0
    for n in news_list:
        if not n["image_url"]:
            n["image_name"] = "default.png"
            fallback += 1
            continue
        image_name = safe_image_filename(n["title"], n["link"])
        if download_and_process_image(n["image_url"], image_name):
            n["image_name"] = image_name
            assigned += 1
        else:
            n["image_name"] = "default.png"
            fallback += 1
    log(f"Image processing finished: {assigned} assigned, {fallback} fallback")


def write_xml(news_list):
    xml_out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<nsx anno="" lt-id="131" min-sys-ver="1" rev="1093" ver="1.0">',
        '\t<spc anno="csxad=1&amp;adspace=9,10,11,12,13" id="33537" multi="o" rep="t">',
    ]

    for i, n in enumerate(news_list):
        picks_anno = ' anno="picks=1"' if i < 3 else ""
        image_url = f"{GITHUB_RAW_PREFIX}{n['image_name']}"
        description_html = f'<img src="{xml_escape(image_url)}">{xml_escape(n["summary"])}'

        xml_out.append(f'\t\t<mtrl id="0" lastm="{xml_escape(n["date"])}" until="2100-12-31T23:59:00.000Z"{picks_anno}>')
        xml_out.append(f'\t\t\t<desc>{xml_escape(n["title"])}</desc>')
        xml_out.append(f'\t\t\t<url type="2">{xml_escape(image_url)}</url>')
        xml_out.append(f'\t\t\t<target type="u">{xml_escape(n["link"])}</target>')
        xml_out.append('\t\t\t<cntry agelmt="0">all</cntry>\t\t\t<lang>all</lang>')
        xml_out.append(f'\t\t\t<description>{description_html}</description>')
        xml_out.append(f'\t\t\t<creators>{xml_escape(n["author"])}</creators>')
        xml_out.append('\t\t</mtrl>')

    xml_out.append('\t</spc>')
    xml_out.append('</nsx>')

    with open(XML_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(xml_out))
    log(f"XML written: {XML_PATH}")


def validate_output():
    if not os.path.exists(XML_PATH):
        log("ERROR: XML file was not created")
        raise SystemExit(1)

    with open(XML_PATH, "r", encoding="utf-8") as f:
        xml_content = f.read()

    material_count = xml_content.count("<mtrl")
    log(f"XML size: {len(xml_content)} chars")
    log(f"XML material count: {material_count}")

    if material_count <= 0:
        log("ERROR: XML was created without any <mtrl> items")
        raise SystemExit(1)

    # Important: this feed intentionally embeds small HTML inside <description>,
    # exactly like the old scraper did, because files/index.html reads it line-by-line
    # and extracts the image with a regex. A strict XML parser would reject raw <img>.
    # So we validate the feed contract used by the site/PS3 reader instead.
    required_closing = ["</mtrl>", "</spc>", "</nsx>"]
    for token in required_closing:
        if token not in xml_content:
            log(f"ERROR: XML output is missing required closing token: {token}")
            raise SystemExit(1)

    desc_count = xml_content.count("<desc>")
    target_count = xml_content.count('<target type="u">')
    description_count = xml_content.count("<description>")
    creator_count = xml_content.count("<creators>")

    log(f"Feed contract counts: desc={desc_count}, target={target_count}, description={description_count}, creators={creator_count}")

    expected_counts = [desc_count, target_count, description_count, creator_count]
    if any(count != material_count for count in expected_counts):
        log("ERROR: Feed contract validation failed; tag counts do not match <mtrl> count")
        raise SystemExit(1)

    log("Feed contract validation: OK")


def update_psx_news():
    log("Starting PSX-Place Scraper v7 with multi-method HTTP fallback")
    log(f"Working directory: {os.getcwd()}")
    log(f"Max pages: {MAX_PAGES}")
    log(f"Max items: {MAX_ITEMS}")
    log(f"Force image refresh: {FORCE_IMAGE_REFRESH}")

    os.makedirs(DIR_FILES, exist_ok=True)
    os.makedirs(DIR_UNCOMPRESSED, exist_ok=True)
    os.makedirs(DIR_COMPRESSED, exist_ok=True)

    news_list = collect_news()
    log(f"Total news found: {len(news_list)}")

    for n in news_list[:5]:
        log(f"Sample article: {n.get('title')} | {n.get('link')} | image={bool(n.get('image_url'))}")

    if not news_list:
        log("ERROR: No news articles were found. Nothing will be saved.")
        raise SystemExit(1)

    process_images(news_list)
    write_xml(news_list)
    validate_output()

    log("Success: XML and images were generated")
    log(f"XML output: {XML_PATH}")
    log(f"Uncompressed images: {DIR_UNCOMPRESSED}")
    log(f"Compressed images: {DIR_COMPRESSED}")


if __name__ == "__main__":
    update_psx_news()
