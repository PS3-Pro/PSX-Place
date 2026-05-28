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
from PIL import Image, ImageOps, UnidentifiedImageError

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
    {
        "engine": "curl_cffi",
        "profile": "safari15_5",
        "name": "safari-macos",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    },
    {
        "engine": "curl_cffi",
        "profile": "chrome124",
        "name": "chrome-windows",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    },
    {
        "engine": "plain_requests",
        "profile": None,
        "name": "plain-safari-headers",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    },
]

TITLE_SELECTORS = [
    "h1 a[href*='/threads/']",
    "h2 a[href*='/threads/']",
    "h3 a[href*='/threads/']",
    "h4 a[href*='/threads/']",
    ".article-title a[href*='/threads/']",
    ".articleTitle a[href*='/threads/']",
    ".porta-title a[href*='/threads/']",
    ".portaTitle a[href*='/threads/']",
    ".message-title a[href*='/threads/']",
    ".contentRow-title a[href*='/threads/']",
    ".structItem-title a[href*='/threads/']",
    "[data-xf-init='preview-tooltip'] a[href*='/threads/']",
    "a[data-tp-primary='on'][href*='/threads/']",
]

BODY_OR_INTERNAL_SELECTORS = [
    ".bbWrapper",
    ".message-body",
    ".message-content",
    ".articleBody",
    ".article-body",
    ".bbCodeBlock",
    ".message-responseRow",
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
    url = urljoin(base, href)
    url = url.split("#")[0]
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def canonical_thread_url(url):
    url = normalize_url(url)
    if not url:
        return ""
    url = re.sub(r"/post-\d+/?$", "/", url)
    url = re.sub(r"/page-\d+/?$", "/", url)
    return url


def portal_url(page):
    if page <= 1:
        return PSX_BASE
    return f"{PSX_BASE}ewr-porta/page-{page}"


def fetch_url(url, timeout=30, binary=False):
    errors = []
    for method in HTTP_METHODS:
        try:
            if method["engine"] == "curl_cffi":
                response = curl_requests.get(
                    url,
                    impersonate=method["profile"],
                    headers=method["headers"],
                    timeout=timeout,
                )
            else:
                response = plain_requests.get(url, headers=method["headers"], timeout=timeout)

            size = len(response.content or b"") if binary else len(response.text or "")
            log(f"GET {url} -> {method['engine']} profile={method['profile']} headers={method['name']} HTTP {response.status_code}, {size} {'bytes' if binary else 'chars'}")

            if response.status_code == 200:
                return response.content if binary else response.text

            errors.append(f"{method['engine']}:{method['name']}:{response.status_code}")
        except Exception as e:
            errors.append(f"{method['engine']}:{method['name']}:{type(e).__name__}")
            log(f"Fetch error with {method['engine']} {method['name']}: {url} -> {e}")

    log(f"All fetch methods failed for {url}: {', '.join(errors)}")
    return b"" if binary else ""


def fetch_html(url, timeout=30):
    return fetch_url(url, timeout=timeout, binary=False)


def is_article_url(url):
    return "/threads/" in (url or "")


def extract_thread_id(url):
    match = re.search(r"\.(\d+)/?(?:post-\d+)?/?$", url)
    if match:
        return match.group(1)
    match = re.search(r"\.(\d+)/", url)
    if match:
        return match.group(1)
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def clean_title(title):
    title = clean_text(title)
    title = title.replace("(Forum Thread)", "").strip()
    title = re.sub(r"\s*\|\s*PSX-Place\s*$", "", title).strip()
    return title


def is_bad_title(text):
    if not text:
        return True
    title = clean_title(text)
    low = title.lower()

    bad_exact = {
        "next", "prev", "previous", "first", "last", "go", "here", "click here",
        "read more", "continue", "like", "quote", "reply", "share", "development thread",
        "recent beta test", "the ps3 version", "ported retroarch", "always running ftp server",
    }

    if low in bad_exact:
        return True
    if len(title) < 18:
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


def is_inside_internal_body(anchor):
    try:
        return anchor.find_parent(BODY_OR_INTERNAL_SELECTORS) is not None
    except Exception:
        return False


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


def is_good_image_url(url):
    if not url:
        return False
    low = url.lower()
    bad_parts = [
        "avatar", "avatars", "smilie", "smilies", "sprite", "logo", "reaction", "styles/",
        "blank.gif", "data:image", "joypixels", "emoji", "giphy", "/xf/", "favicon",
    ]
    if any(part in low for part in bad_parts):
        return False
    if low.endswith(".gif") or low.endswith(".svg") or low.endswith(".webp"):
        return False
    if "psx-place.com" in low and ("/attachments/" in low or "/data/features/" in low or "/data/attachments/" in low or "/ewr-porta/attachments/" in low):
        return True
    if low.endswith(('.jpg', '.jpeg', '.png')) or '.jpg?' in low or '.png?' in low:
        return True
    return False


def normalize_image_url(src, base_url=PSX_BASE):
    if not src:
        return ""
    src = src.strip().strip('"\'')
    if src.startswith("//"):
        src = "https:" + src
    return normalize_url(src, base_url)


def score_image_url(url):
    low = (url or "").lower()
    if not is_good_image_url(url):
        return -1000
    score = 0
    if "/data/features/" in low:
        score += 100
    if "/attachments/" in low:
        score += 80
    if "/ewr-porta/attachments/" in low:
        score += 75
    if "/data/attachments/" in low:
        score += 70
    if low.endswith(".jpg") or low.endswith(".jpeg"):
        score += 15
    if low.endswith(".png"):
        score += 10
    return score


def extract_style_urls(text, base_url=PSX_BASE):
    urls = []
    if not text:
        return urls
    for match in re.findall(r"url\((['\"]?)(.*?)\1\)", text, flags=re.I | re.S):
        raw = match[1]
        url = normalize_image_url(raw, base_url)
        if is_good_image_url(url):
            urls.append(url)
    return urls


def extract_images_from_node(node, base_url=PSX_BASE):
    candidates = []
    if not node:
        return candidates

    nodes = [node]
    try:
        nodes.extend(node.find_all(True))
    except Exception:
        pass

    for el in nodes:
        style = el.get("style") if hasattr(el, "get") else ""
        for url in extract_style_urls(style, base_url):
            candidates.append(url)

        if not hasattr(el, "get"):
            continue

        for attr in ("src", "data-src", "data-url", "data-original", "data-background-image"):
            value = el.get(attr)
            if value:
                url = normalize_image_url(value, base_url)
                if is_good_image_url(url):
                    candidates.append(url)

        srcset = el.get("srcset")
        if srcset:
            for part in srcset.split(','):
                raw = part.strip().split(' ')[0]
                url = normalize_image_url(raw, base_url)
                if is_good_image_url(url):
                    candidates.append(url)

    return candidates


def best_image(candidates):
    unique = []
    seen = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)
    if not unique:
        return ""
    unique.sort(key=score_image_url, reverse=True)
    return unique[0] if score_image_url(unique[0]) > 0 else ""


def image_near_anchor(anchor, page_html=""):
    candidates = []

    # 1) Walk upward from the title link. The first article/card ancestor usually contains the card image.
    current = anchor
    for depth in range(0, 7):
        if current is None:
            break
        candidates.extend(extract_images_from_node(current, PSX_BASE))
        img = best_image(candidates)
        if img:
            log(f"Selected portal image near title at ancestor depth {depth}: {img}")
            return img
        current = current.parent

    # 2) Look at nearby siblings around the title link/heading. XenPorta sometimes stores card images as CSS backgrounds.
    nearby_nodes = []
    parent = anchor.parent
    for _ in range(0, 4):
        if not parent:
            break
        for sib in list(parent.previous_siblings)[-5:]:
            if getattr(sib, "name", None):
                nearby_nodes.append(sib)
        for sib in list(parent.next_siblings)[:5]:
            if getattr(sib, "name", None):
                nearby_nodes.append(sib)
        parent = parent.parent

    for node in nearby_nodes:
        candidates.extend(extract_images_from_node(node, PSX_BASE))
    img = best_image(candidates)
    if img:
        log(f"Selected portal image from nearby sibling: {img}")
        return img

    # 3) Raw HTML window around the title link. This catches background-image URLs that BeautifulSoup may not group well.
    href = anchor.get("href") or ""
    search_terms = [href, href.replace("&", "&amp;")]
    absolute = normalize_url(href)
    if absolute:
        search_terms.append(absolute)

    for term in search_terms:
        if not term:
            continue
        pos = page_html.find(term)
        if pos == -1:
            continue
        window = page_html[max(0, pos - 4500): pos + 2500]
        local = []
        for attr_url in re.findall(r"(?:src|data-src|data-url|data-original|data-background-image)=['\"]([^'\"]+)['\"]", window, flags=re.I):
            url = normalize_image_url(attr_url, PSX_BASE)
            if is_good_image_url(url):
                local.append(url)
        local.extend(extract_style_urls(window, PSX_BASE))
        img = best_image(local)
        if img:
            log(f"Selected portal image from raw HTML window: {img}")
            return img

    return ""


def get_thread_feature_guess(link):
    thread_id = extract_thread_id(link)
    if not thread_id:
        return ""
    return f"{PSX_BASE}data/features/{thread_id}.jpg"


def extract_portal_links(soup, page_html):
    found = []
    seen = set()
    raw_thread_hrefs = len(soup.select("a[href*='/threads/']"))
    selector_hits = 0

    for selector in TITLE_SELECTORS:
        anchors = soup.select(selector)
        selector_hits += len(anchors)
        for a in anchors:
            if is_inside_internal_body(a):
                continue
            href = canonical_thread_url(a.get("href"))
            title = clean_title(a.get("title") or a.get_text(" ", strip=True))

            if not is_article_url(href) or is_bad_title(title):
                continue
            if href in seen:
                continue

            image_url = image_near_anchor(a, page_html)
            image_source = "portal"

            # Some valid XenPorta cards expose the image only as /data/features/{thread_id}.jpg.
            # This is used only for title-selector matches, not for random body links.
            if not image_url:
                image_url = get_thread_feature_guess(href)
                image_source = "feature-guess"
                log(f"Using feature-image guess for home-card title: {title} -> {image_url}")

            seen.add(href)
            found.append({
                "title": title,
                "link": href,
                "portal_image_url": image_url,
                "image_source": image_source,
            })

    # Conservative fallback: if selector classes change, accept heading links only, never body links.
    if len(found) < 3:
        for a in soup.select("a[href*='/threads/']"):
            if is_inside_internal_body(a):
                continue
            parent_name = (a.parent.name or "").lower() if a.parent else ""
            if parent_name not in {"h1", "h2", "h3", "h4"}:
                continue
            href = canonical_thread_url(a.get("href"))
            title = clean_title(a.get("title") or a.get_text(" ", strip=True))
            if not is_article_url(href) or is_bad_title(title) or href in seen:
                continue
            image_url = image_near_anchor(a, page_html) or get_thread_feature_guess(href)
            seen.add(href)
            found.append({
                "title": title,
                "link": href,
                "portal_image_url": image_url,
                "image_source": "heading-fallback",
            })

    log(f"Portal extraction debug: raw thread hrefs seen={raw_thread_hrefs}, selector hits={selector_hits}, accepted home-card titles={len(found)}")
    return found


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
            if name and len(name) <= 50:
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
        return {
            "title": clean_title(item["title"]),
            "link": item["link"],
            "image_url": item.get("portal_image_url", ""),
            "image_name": "default.png",
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
    image_url = item.get("portal_image_url", "")

    return {
        "title": title,
        "link": item["link"],
        "image_url": image_url,
        "image_name": "default.png",
        "author": author,
        "summary": summary,
        "date": date,
    }


def make_image_name(title, link):
    thread_id = extract_thread_id(link)
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", clean_title(title))
    safe_title = re.sub(r"_+", "_", safe_title).strip("._-")
    safe_title = safe_title[:88] or "psx_place"
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
    path_uncompressed = os.path.join(DIR_UNCOMPRESSED, image_name)
    path_compressed = os.path.join(DIR_COMPRESSED, image_name)

    if not image_url:
        return False

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
        content = fetch_url(image_url, timeout=25, binary=True)
        if not content:
            return False
        try:
            img = Image.open(BytesIO(content))
        except UnidentifiedImageError:
            log(f"Image content is not readable by PIL: {image_url}")
            return False
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
        links = extract_portal_links(soup, html)
        log(f"Portal page {current_page}: found {len(links)} home-card titles")

        if not links and current_page > 1:
            log("No more article cards found, stopping pagination")
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
        log(f"Article detail {i}/{len(seeds)}: {item['title'][:100]} | image_source={item.get('image_source')}")
        news = read_article_detail(item)
        news_list.append(news)
        time.sleep(DETAIL_DELAY)

    return news_list


def process_images(news_list):
    log(f"Processing images for {len(news_list)} articles")
    assigned = 0
    fallback = 0
    for n in news_list:
        if not n.get("image_url"):
            n["image_name"] = "default.png"
            fallback += 1
            continue

        image_name = make_image_name(n["title"], n["link"])
        if download_and_process_image(n["image_url"], image_name):
            n["image_name"] = image_name
            assigned += 1
        else:
            # Last-resort feature guess if the portal image URL was stale/missing.
            guessed = get_thread_feature_guess(n["link"])
            guessed_name = make_image_name(n["title"], n["link"])
            if guessed != n.get("image_url") and download_and_process_image(guessed, guessed_name):
                n["image_name"] = guessed_name
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


def validate_feed_contract():
    if not os.path.exists(XML_PATH):
        log("ERROR: XML file was not created")
        raise SystemExit(1)

    with open(XML_PATH, "r", encoding="utf-8") as f:
        xml_content = f.read()

    material_count = xml_content.count("<mtrl")
    description_count = xml_content.count("<description>")
    creator_count = xml_content.count("<creators>")

    log(f"XML size: {len(xml_content)} chars")
    log(f"XML material count: {material_count}")
    log(f"XML description count: {description_count}")
    log(f"XML creators count: {creator_count}")

    if material_count <= 0:
        log("ERROR: XML was created without any <mtrl> items")
        raise SystemExit(1)
    if description_count != material_count or creator_count != material_count:
        log("ERROR: Feed contract validation failed: item tag counts do not match")
        raise SystemExit(1)
    if "</spc>" not in xml_content or "</nsx>" not in xml_content:
        log("ERROR: Feed contract validation failed: closing tags are missing")
        raise SystemExit(1)

    log("Feed contract validation: OK")


def update_psx_news():
    log("Starting PSX-Place Scraper v12 card-title + portal-image recovery")
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
        log("ERROR: No portal article titles were found. Nothing will be saved.")
        raise SystemExit(1)

    process_images(news_list)
    write_xml(news_list)
    validate_feed_contract()

    log("Success: XML and images were generated")
    log(f"XML output: {XML_PATH}")
    log(f"Uncompressed images: {DIR_UNCOMPRESSED}")
    log(f"Compressed images: {DIR_COMPRESSED}")


if __name__ == "__main__":
    update_psx_news()
