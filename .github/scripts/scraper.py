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

HTTP_METHODS = [
    (
        "curl_cffi",
        "safari15_5",
        "safari-macos",
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    ),
    (
        "curl_cffi",
        "safari17_0",
        "safari-macos",
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    ),
    (
        "curl_cffi",
        "chrome124",
        "chrome-windows",
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    ),
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
    return escape(str(text or ""), {
        '"': "&quot;",
        "'": "&apos;",
    })


def normalize_url(href, base=PSX_BASE):
    if not href:
        return ""

    url = urljoin(base, href)
    url = url.split("#")[0]
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def canonical_thread_url(url):
    url = normalize_url(url)
    if not url:
        return ""

    # Keep only the canonical /threads/title.id/ portion.
    m = re.search(r"(https?://[^/]+/threads/[^/]+\.\d+/)", url)
    if m:
        return m.group(1)

    # Some malformed links can miss the final slash.
    m = re.search(r"(https?://[^/]+/threads/[^/]+\.\d+)", url)
    if m:
        return m.group(1) + "/"

    return url


def extract_thread_id(url):
    m = re.search(r"\.(\d+)/?(?:$|post-|page-)", url)
    if m:
        return m.group(1)

    m = re.search(r"\.(\d+)", url)
    if m:
        return m.group(1)

    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def portal_url(page):
    if page <= 1:
        return PSX_BASE
    return f"{PSX_BASE}ewr-porta/page-{page}"


def fetch_html(url, timeout=30):
    last_status = "none"
    last_size = 0

    for method_name, profile, header_name, headers in HTTP_METHODS:
        try:
            response = curl_requests.get(
                url,
                impersonate=profile,
                timeout=timeout,
                headers=headers,
            )
            html = response.text or ""
            last_status = str(response.status_code)
            last_size = len(html)
            log(f"GET {url} -> {method_name} profile={profile} headers={header_name} HTTP {response.status_code}, {len(html)} chars")

            if response.status_code == 200 and html:
                return html

        except Exception as e:
            log(f"GET error {url} -> {method_name} profile={profile} headers={header_name}: {type(e).__name__}: {e}")

    log(f"Giving up: {url} last_status={last_status} last_size={last_size}")
    return ""


def fetch_bytes(url, timeout=30):
    for method_name, profile, header_name, headers in HTTP_METHODS:
        try:
            response = curl_requests.get(
                url,
                impersonate=profile,
                timeout=timeout,
                headers=headers,
            )
            content = response.content or b""
            log(f"Image GET {url} -> {method_name} profile={profile} HTTP {response.status_code}, {len(content)} bytes")

            if response.status_code == 200 and content:
                return content

        except Exception as e:
            log(f"Image GET error {url} -> {method_name} profile={profile}: {type(e).__name__}: {e}")

    return b""


def is_article_url(url):
    return "/threads/" in url and re.search(r"\.\d+/?", url) is not None


def is_bad_title(text):
    if not text:
        return True

    title = clean_text(text)
    low = title.lower()

    if len(title) < 15:
        return True

    bad_exact = {
        "next", "prev", "previous", "first", "last", "go", "here",
        "click here", "read more", "continue", "like", "quote", "reply",
        "share", "forum link", "github link", "development thread",
        "recent beta test", "the ps3 version", "ported retroarch",
        "always running ftp server", "overclock your ps vita",
    }

    if low in bad_exact:
        return True

    bad_starts = (
        "update (",
        "also here",
        "see also",
        "this thread",
        "forum thread",
    )

    if low.startswith(bad_starts):
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


def is_good_image_url(url):
    if not url:
        return False

    low = url.lower()

    bad_parts = [
        "avatar",
        "avatars",
        "smilie",
        "smilies",
        "sprite",
        "logo",
        "reaction",
        "styles/",
        "blank.gif",
        "data:image",
        "joypixels",
        "emoji",
        "emojione",
        "twemoji",
        "giphy",
        "cdn.jsdelivr.net/joypixels",
    ]

    if any(part in low for part in bad_parts):
        return False

    bad_ext = (".gif", ".svg", ".webp")
    if low.endswith(bad_ext):
        return False

    return True


def get_img_src(img, base_url=PSX_BASE):
    for attr in ("data-url", "data-src", "src"):
        src = img.get(attr)
        if src:
            return normalize_url(src, base_url)
    return ""


def extract_urls_from_style(style, base_url=PSX_BASE):
    urls = []
    if not style:
        return urls

    for match in re.finditer(r"url\((['\"]?)(.*?)\1\)", style):
        raw = match.group(2).strip()
        if raw:
            urls.append(normalize_url(raw, base_url))

    return urls


def find_images_near_link(link_tag, soup):
    candidates = []

    # First inspect the link and its parents. This catches images and background images in real portal cards.
    current = link_tag
    for depth in range(0, 7):
        if current is None:
            break

        for img in current.select("img") if hasattr(current, "select") else []:
            src = get_img_src(img)
            if is_good_image_url(src):
                candidates.append(("near-img", src))

        if hasattr(current, "attrs"):
            for src in extract_urls_from_style(current.get("style", "")):
                if is_good_image_url(src):
                    candidates.append(("near-style", src))

        if hasattr(current, "select"):
            for styled in current.select("[style*='url']"):
                for src in extract_urls_from_style(styled.get("style", "")):
                    if is_good_image_url(src):
                        candidates.append(("near-style-child", src))

        current = current.parent

    # If the page uses a feature path by thread id, try it as a lightweight candidate.
    thread_id = extract_thread_id(link_tag.get("href", ""))
    if thread_id and thread_id.isdigit():
        candidates.append(("feature-guess", f"{PSX_BASE}data/features/{thread_id}.jpg"))

    # Deduplicate while preserving order.
    out = []
    seen = set()
    for source, src in candidates:
        if src in seen:
            continue
        seen.add(src)
        out.append((source, src))

    return out


def is_inside_body_text(tag):
    bad_selectors = [
        ".bbWrapper",
        ".message-body",
        ".message-content",
        ".message-main",
        ".js-lbContainer",
        ".block-body",
        ".articleBody",
        "[itemprop='articleBody']",
    ]

    for parent in tag.parents:
        if not getattr(parent, "select_one", None):
            continue

        classes = " ".join(parent.get("class", [])) if parent.get("class") else ""
        class_low = classes.lower()

        if "bbwrapper" in class_low or "message-body" in class_low or "articlebody" in class_low:
            return True

        for selector in bad_selectors:
            try:
                if parent.select_one(selector) is not None and parent.select_one(selector) is not tag:
                    # This parent contains a body wrapper; only treat as body if the link is inside that wrapper.
                    nearest = tag.find_parent(selector)
                    if nearest is not None:
                        return True
            except Exception:
                pass

    return False


def is_probably_portal_link(a):
    if not a or not a.get("href"):
        return False

    href = normalize_url(a.get("href"))
    if not is_article_url(href):
        return False

    if "/post-" in href:
        return False

    title = clean_text(a.get("title") or a.get_text(" ", strip=True))

    if is_bad_title(title):
        return False

    # Links inside content summaries are usually references to older threads, not home-card entries.
    if is_inside_body_text(a):
        return False

    return True


def extract_portal_links(soup):
    found = []
    seen = set()

    # Use a broad scan because PSX-Place/XenPorta markup changes often.
    raw_thread_hrefs = 0
    no_image = 0

    for a in soup.select("a[href*='/threads/']"):
        href_raw = normalize_url(a.get("href"))
        raw_thread_hrefs += 1

        if not is_probably_portal_link(a):
            continue

        canonical = canonical_thread_url(href_raw)
        if canonical in seen:
            continue

        title = clean_text(a.get("title") or a.get_text(" ", strip=True))
        image_candidates = find_images_near_link(a, soup)
        image_url = ""

        for source, candidate in image_candidates:
            if is_good_image_url(candidate):
                image_url = candidate
                break

        if not image_url:
            no_image += 1
            log(f"Skipping article without portal image candidate: {title} | {canonical}")
            continue

        seen.add(canonical)
        found.append({
            "title": title,
            "link": canonical,
            "portal_image_url": image_url,
        })

        if len(found) <= 8:
            log(f"Accepted portal article: {title} | image={image_url}")

    log(
        f"Portal extraction debug: raw thread hrefs seen={raw_thread_hrefs}, "
        f"accepted={len(found)}, skipped_no_image={no_image}"
    )

    return found


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
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except Exception:
        return "1970-01-01T00:00:00.000Z"


def clean_title(title):
    title = clean_text(title)
    title = title.replace("(Forum Thread)", "").strip()
    title = re.sub(r"\s*\|\s*PSX-Place\s*$", "", title).strip()
    return title


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
    if meta_desc:
        return meta_desc[:900]

    return ""


def extract_author(soup):
    author = get_meta_content(soup, "author", "article:author")
    if author:
        return author

    selectors = [
        "a.username",
        ".message-name a",
        ".message-userDetails a.username",
        ".p-description a[href*='/members/']",
        "a[href*='/members/']",
    ]

    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            name = clean_text(tag.get_text(" ", strip=True))
            if name and len(name) <= 40:
                return name

    return "PSX-Place"


def extract_article_date(soup):
    date_value = get_meta_content(
        soup,
        "article:published_time",
        "article:modified_time",
        "og:updated_time",
    )

    if date_value:
        return parse_date_to_ps3(date_value)

    time_tag = soup.select_one("time[datetime]")
    if time_tag and time_tag.get("datetime"):
        return parse_date_to_ps3(time_tag.get("datetime"))

    return "1970-01-01T00:00:00.000Z"


def read_article_detail(item):
    html = fetch_html(item["link"], timeout=30)

    if not html:
        log(f"Could not open article, skipping later if image fails: {item['link']}")
        return {
            "title": clean_title(item["title"]),
            "link": item["link"],
            "image_url": item.get("portal_image_url", ""),
            "image_name": "",
            "author": "PSX-Place",
            "summary": clean_title(item["title"]),
            "date": "1970-01-01T00:00:00.000Z",
        }

    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.select_one("h1.p-title-value") or soup.select_one("h1")
    title = clean_title(title_tag.get_text(" ", strip=True) if title_tag else item["title"])

    if not title:
        title = clean_title(get_meta_content(soup, "og:title") or item["title"])

    summary = extract_summary(soup) or title
    author = extract_author(soup)
    date = extract_article_date(soup)

    return {
        "title": title,
        "link": item["link"],
        "image_url": item.get("portal_image_url", ""),
        "image_name": "",
        "author": author,
        "summary": summary,
        "date": date,
    }


def make_image_name(title, link):
    thread_id = extract_thread_id(link)
    safe_title = re.sub(r"[\\/*?:\"<>|&{}\[\]#+=]", "", title)
    safe_title = re.sub(r"[^A-Za-z0-9._ -]+", "", safe_title)
    safe_title = re.sub(r"\s+", "_", safe_title).strip("._- ")
    safe_title = safe_title[:80] or "psx_place"

    return f"{thread_id}_{safe_title}.jpg"


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
    if not image_url or not is_good_image_url(image_url):
        return False

    path_uncompressed = os.path.join(DIR_UNCOMPRESSED, image_name)
    path_compressed = os.path.join(DIR_COMPRESSED, image_name)

    if not FORCE_IMAGE_REFRESH and os.path.exists(path_uncompressed) and os.path.exists(path_compressed):
        log(f"Image already exists, skipping download: {image_name}")
        return True

    if not FORCE_IMAGE_REFRESH and os.path.exists(path_uncompressed) and not os.path.exists(path_compressed):
        try:
            log(f"Rebuilding compressed image from existing original: {image_name}")
            img = Image.open(path_uncompressed)
            save_jpeg_versions(img, path_uncompressed, path_compressed)
            return True
        except Exception as e:
            log(f"Could not rebuild compressed image, downloading again: {image_name} -> {e}")

    content = fetch_bytes(image_url, timeout=30)
    if not content:
        return False

    try:
        img = Image.open(BytesIO(content))
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
        log(f"Portal page {current_page}: found {len(links)} image-backed portal articles")

        if not links and current_page > 1:
            log("No more portal articles found, stopping pagination")
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

    kept = []
    skipped_no_image = 0
    skipped_download = 0

    for n in news_list:
        image_url = n.get("image_url", "")

        if not image_url:
            skipped_no_image += 1
            log(f"Skipping article without image URL: {n.get('title')}")
            continue

        image_name = make_image_name(n["title"], n["link"])

        if download_and_process_image(image_url, image_name):
            n["image_name"] = image_name
            kept.append(n)
        else:
            skipped_download += 1
            log(f"Skipping article because image could not be downloaded/decoded: {n.get('title')} | {image_url}")

    log(
        f"Image processing finished: kept={len(kept)}, "
        f"skipped_no_image={skipped_no_image}, skipped_download={skipped_download}"
    )

    return kept


def write_xml(news_list):
    xml_out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<nsx anno="" lt-id="131" min-sys-ver="1" rev="1093" ver="1.0">',
        '\t<spc anno="csxad=1&amp;adspace=9,10,11,12,13" id="33537" multi="o" rep="t">',
    ]

    for i, n in enumerate(news_list):
        picks_anno = ' anno="picks=1"' if i < 3 else ""
        image_url = f"{GITHUB_RAW_PREFIX}{n['image_name']}"

        # Keep the historical PS3 feed contract: the HTML reads the <img src=""> string directly.
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


def validate_feed_contract(min_items=1):
    if not os.path.exists(XML_PATH):
        log("ERROR: XML file was not created")
        raise SystemExit(1)

    with open(XML_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    material_count = content.count("<mtrl")
    default_count = content.count("default.png")

    log(f"XML size: {len(content)} chars")
    log(f"XML material count: {material_count}")
    log(f"XML default image references: {default_count}")

    if material_count < min_items:
        log("ERROR: XML was created without enough <mtrl> items")
        raise SystemExit(1)

    if default_count > 0:
        log("ERROR: default.png was found in the XML. This feed only accepts real images.")
        raise SystemExit(1)

    required = ["</spc>", "</nsx>", "<description>", "<creators>"]
    for token in required:
        if token not in content:
            log(f"ERROR: Feed contract token missing: {token}")
            raise SystemExit(1)

    log("Feed contract validation: OK")


def update_psx_news():
    log("Starting PSX-Place Scraper v14 real-images-only")
    log(f"Working directory: {os.getcwd()}")
    log(f"Max pages: {MAX_PAGES}")
    log(f"Max items: {MAX_ITEMS}")
    log(f"Force image refresh: {FORCE_IMAGE_REFRESH}")

    os.makedirs(DIR_FILES, exist_ok=True)
    os.makedirs(DIR_UNCOMPRESSED, exist_ok=True)
    os.makedirs(DIR_COMPRESSED, exist_ok=True)

    news_list = collect_news()

    log(f"Total news found before image filtering: {len(news_list)}")

    for n in news_list[:8]:
        log(f"Sample article before filtering: {n.get('title')} | {n.get('link')} | image={n.get('image_url')}")

    if not news_list:
        log("ERROR: No portal articles were found. Nothing will be saved.")
        raise SystemExit(1)

    news_list = process_images(news_list)

    log(f"Total news kept after image filtering: {len(news_list)}")

    for n in news_list[:8]:
        log(f"Sample kept article: {n.get('title')} | image_name={n.get('image_name')}")

    if not news_list:
        log("ERROR: All articles were skipped because none had valid real images.")
        raise SystemExit(1)

    write_xml(news_list)
    validate_feed_contract(min_items=1)

    log("Success: XML and real images were generated")
    log(f"XML output: {XML_PATH}")
    log(f"Uncompressed images: {DIR_UNCOMPRESSED}")
    log(f"Compressed images: {DIR_COMPRESSED}")


if __name__ == "__main__":
    update_psx_news()
