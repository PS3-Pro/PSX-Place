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

HEADER_SETS = [
    (
        "safari-macos",
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    ),
    (
        "chrome-windows",
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": PSX_BASE,
        },
    ),
]

CURL_PROFILES = [
    "safari15_5",
    "safari17_0",
    "chrome120",
    "chrome124",
    "chrome131",
]

BAD_TITLES = {
    "next",
    "prev",
    "previous",
    "first",
    "last",
    "go",
    "here",
    "click here",
    "read more",
    "continue",
    "like",
    "quote",
    "reply",
    "share",
    "download",
    "source",
}


# -----------------------------
# Logging helpers
# -----------------------------

def now_stamp():
    return datetime.now().strftime("%H:%M:%S")


def log(message):
    print(f"[{now_stamp()}] {message}", flush=True)


# -----------------------------
# Text / URL helpers
# -----------------------------

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


def portal_url(page):
    if page <= 1:
        return PSX_BASE
    return f"{PSX_BASE}ewr-porta/page-{page}"


def canonical_thread_url(url):
    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path

    if "/threads/" not in path:
        return ""

    match = re.search(r"(/threads/[^/?#]+?\.\d+)(?:/.*)?$", path)
    if not match:
        return ""

    canonical_path = match.group(1)
    if not canonical_path.endswith("/"):
        canonical_path += "/"

    return f"{parsed.scheme}://{parsed.netloc}{canonical_path}"


def extract_thread_id(url):
    match = re.search(r"\.(\d+)/?$", url)
    if match:
        return match.group(1)

    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def title_from_thread_url(url):
    parsed = urlparse(url)
    match = re.search(r"/threads/([^/]+?)\.\d+/?$", parsed.path)

    if not match:
        return "PSX-Place Article"

    slug = match.group(1)
    title = slug.replace("-", " ").replace("_", " ")
    title = clean_text(title)

    # Keep this as a readable fallback only. The real article title is loaded from the thread page later.
    return title[:1].upper() + title[1:] if title else "PSX-Place Article"


def clean_title(title):
    title = clean_text(title)
    title = title.replace("(Forum Thread)", "").strip()
    title = re.sub(r"\s*\|\s*PSX-Place\s*$", "", title).strip()
    return title


def is_bad_title(text):
    title = clean_text(text)
    if not title:
        return True

    low = title.lower()

    if low in BAD_TITLES:
        return True

    if len(title) < 5:
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


def safe_image_file_name(title, link):
    thread_id = extract_thread_id(link)
    safe_title = clean_title(title)
    safe_title = re.sub(r"[^A-Za-z0-9._ -]+", "", safe_title)
    safe_title = re.sub(r"\s+", "_", safe_title).strip("._-")
    safe_title = safe_title[:88] or "psx_place"
    return f"{thread_id}_{safe_title}.jpg"


# -----------------------------
# HTTP
# -----------------------------

def fetch_html(url, timeout=30):
    # Most reliable method first. It matched the successful GitHub Actions run.
    for profile in CURL_PROFILES:
        for header_name, headers in HEADER_SETS:
            try:
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    headers=headers,
                    timeout=timeout,
                )
                html = response.text or ""
                log(
                    f"GET {url} -> curl_cffi profile={profile} "
                    f"headers={header_name} HTTP {response.status_code}, {len(html)} chars"
                )

                if response.status_code == 200 and html:
                    return html
            except Exception as e:
                log(f"curl_cffi error for {url} profile={profile} headers={header_name}: {e}")

    for header_name, headers in HEADER_SETS:
        try:
            response = plain_requests.get(url, headers=headers, timeout=timeout)
            html = response.text or ""
            log(f"GET {url} -> requests headers={header_name} HTTP {response.status_code}, {len(html)} chars")

            if response.status_code == 200 and html:
                return html
        except Exception as e:
            log(f"requests error for {url} headers={header_name}: {e}")

    log(f"Giving up after all HTTP methods failed: {url}")
    return ""


def fetch_binary(url, timeout=25):
    for profile in CURL_PROFILES[:2]:
        for header_name, headers in HEADER_SETS:
            try:
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    headers=headers,
                    timeout=timeout,
                )
                content = response.content or b""
                log(
                    f"Image GET {url} -> curl_cffi profile={profile} "
                    f"headers={header_name} HTTP {response.status_code}, {len(content)} bytes"
                )

                if response.status_code == 200 and content:
                    return content
            except Exception as e:
                log(f"Image curl_cffi error for {url}: {e}")

    for header_name, headers in HEADER_SETS:
        try:
            response = plain_requests.get(url, headers=headers, timeout=timeout)
            content = response.content or b""
            log(f"Image GET {url} -> requests headers={header_name} HTTP {response.status_code}, {len(content)} bytes")

            if response.status_code == 200 and content:
                return content
        except Exception as e:
            log(f"Image requests error for {url}: {e}")

    return b""


# -----------------------------
# Portal link extraction
# -----------------------------

def score_candidate(anchor, title, source_name, was_derived):
    score = 0

    if source_name != "all-links-fallback":
        score += 10

    if not was_derived:
        score += 5

    if len(title) >= 20:
        score += 2

    # Prefer title/header links over body links.
    parent = anchor.parent
    if parent and getattr(parent, "name", "") in {"h1", "h2", "h3"}:
        score += 6

    classes = " ".join(anchor.get("class", [])) + " " + " ".join(parent.get("class", []) if parent else [])
    classes = classes.lower()
    if any(token in classes for token in ["title", "porta", "article", "contentrow", "structitem"]):
        score += 3

    href = anchor.get("href") or ""
    if "/post-" not in href:
        score += 1

    return score


BODY_OR_INTERNAL_SELECTORS = [
    ".bbWrapper",
    ".message-body",
    ".message-content",
    ".articleBody",
    ".article-body",
    ".bbCodeBlock",
    ".message-responseRow",
    ".fr-view",
]

INTERNAL_CONTEXT_MARKERS = [
    "forum link",
    "github link",
    "spoiler:",
    "see updates",
    "view details below",
    ">here<",
]

REAL_TITLE_PREFIXES = (
    "ps5 ", "ps4 ", "ps3 ", "ps2 ", "ps1 ", "psp ",
    "ps vita", "ps vita / ps tv", "ps vita / pstv", "notice ",
    "released", "update", "cfw", "ofw", "hfw", "hen",
)


def is_inside_internal_body(anchor):
    try:
        return anchor.find_parent(BODY_OR_INTERNAL_SELECTORS) is not None
    except Exception:
        return False


def internal_context_score(anchor):
    score = 0
    try:
        parent_text = clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else "")
        low = parent_text.lower()
        if any(marker in low for marker in INTERNAL_CONTEXT_MARKERS):
            score += 5
        if re.search(r"update\s*\([^)]+\)\s*-", low):
            score += 4
        if "(forum thread)" in low or "(forum link)" in low:
            score += 4
        if parent_text.count("UPDATE") >= 2 or parent_text.count("Update") >= 2:
            score += 2
    except Exception:
        pass
    return score


def is_probably_navigation_or_profile(anchor):
    href = (anchor.get("href") or "").lower()
    text = clean_text(anchor.get_text(" ", strip=True)).lower()
    if any(part in href for part in ["/members/", "/forums/", "/tags/", "/login", "/register", "/whats-new", "/resources", "/media"]):
        return True
    if text in BAD_TITLES:
        return True
    return False


def is_probably_real_portal_title(title, info):
    low = title.lower().strip()
    if is_bad_title(title):
        return False

    # Very short generic links are usually inline references, not portal cards.
    bad_short_phrases = {
        "recent beta test",
        "development thread",
        "the ps3 version",
        "ported retroarch",
        "kyuhen homebrew contest",
        "overclock your ps vita",
        "always running ftp server",
        "our great friend and an awesome contributor",
        "fsw-vita - port of shadow warrior classic",
    }
    if low in bad_short_phrases:
        return False

    # Good portal cards usually have either duplicate anchors for image/title or a title-like CSS/source hit.
    if info.get("occurrences", 0) >= 2:
        return True
    if info.get("strong_source", False):
        return True
    if low.startswith(REAL_TITLE_PREFIXES) and len(title) >= 18:
        return True
    if len(title) >= 45 and not info.get("derived", False):
        return True

    return False


def score_candidate(anchor, title, source_name, was_derived):
    score = 0

    if source_name != "all-links-fallback":
        score += 10

    if not was_derived:
        score += 5

    if len(title) >= 20:
        score += 2

    parent = anchor.parent
    if parent and getattr(parent, "name", "") in {"h1", "h2", "h3", "h4"}:
        score += 7

    classes = " ".join(anchor.get("class", [])) + " " + " ".join(parent.get("class", []) if parent else [])
    classes = classes.lower()
    if any(token in classes for token in ["title", "porta", "article", "contentrow", "structitem", "blocklink", "node-title"]):
        score += 4

    # Links inside the article body are usually references mentioned inside a post, not portal cards.
    if is_inside_internal_body(anchor):
        score -= 40

    score -= internal_context_score(anchor) * 5

    href = anchor.get("href") or ""
    if "/post-" not in href:
        score += 1
    else:
        score -= 4

    if is_probably_navigation_or_profile(anchor):
        score -= 100

    return score


def extract_portal_links(soup):
    raw_thread_href_count = 0
    records = {}

    selector_groups = [
        ("headline-links", "h1 a[href], h2 a[href], h3 a[href], h4 a[href]"),
        ("porta-links", "[class*='porta'] a[href], [class*='article'] a[href], [class*='contentRow'] a[href], [class*='structItem'] a[href], [class*='blockLink'] a[href]"),
        ("all-links-fallback", "a[href]"),
    ]

    order = 0
    for source_name, selector in selector_groups:
        for anchor in soup.select(selector):
            order += 1
            href = anchor.get("href") or ""
            absolute_url = normalize_url(href)

            if "threads" in absolute_url:
                raw_thread_href_count += 1

            canonical_url = canonical_thread_url(absolute_url)
            if not canonical_url:
                continue

            if is_probably_navigation_or_profile(anchor):
                continue

            raw_title = clean_title(anchor.get("title") or anchor.get_text(" ", strip=True))
            was_derived = False
            if is_bad_title(raw_title):
                title = title_from_thread_url(canonical_url)
                was_derived = True
            else:
                title = raw_title

            if is_bad_title(title):
                continue

            score = score_candidate(anchor, title, source_name, was_derived)

            rec = records.setdefault(canonical_url, {
                "title": title,
                "link": canonical_url,
                "best_score": -9999,
                "score_sum": 0,
                "occurrences": 0,
                "meaningful_titles": 0,
                "body_hits": 0,
                "strong_source": False,
                "derived": True,
                "first_order": order,
                "sources": set(),
            })

            rec["occurrences"] += 1
            rec["score_sum"] += score
            rec["sources"].add(source_name)
            rec["body_hits"] += 1 if is_inside_internal_body(anchor) else 0
            rec["strong_source"] = rec["strong_source"] or source_name != "all-links-fallback"
            rec["derived"] = rec["derived"] and was_derived
            rec["first_order"] = min(rec["first_order"], order)

            if not was_derived:
                rec["meaningful_titles"] += 1

            if score > rec["best_score"] or (score == rec["best_score"] and len(title) > len(rec["title"])):
                rec["title"] = title
                rec["best_score"] = score

    accepted = []
    rejected_internal = 0
    rejected_weak = 0

    for rec in records.values():
        # If every occurrence came from inside article text, it is almost certainly an inline reference.
        if rec["body_hits"] >= rec["occurrences"] and rec["occurrences"] < 2:
            rejected_internal += 1
            continue

        # Require at least one non-derived readable title.
        if rec["meaningful_titles"] <= 0:
            rejected_weak += 1
            continue

        if not is_probably_real_portal_title(rec["title"], rec):
            rejected_weak += 1
            continue

        # Strongly reject body-only update/reference links even if their title is long.
        if rec["best_score"] < -10:
            rejected_internal += 1
            continue

        accepted.append(rec)

    accepted.sort(key=lambda x: (x["first_order"], -x["best_score"]))

    unique = []
    for item in accepted[:MAX_ITEMS]:
        unique.append({"title": item["title"], "link": item["link"]})

    log(
        "Portal extraction debug: "
        f"raw thread hrefs seen={raw_thread_href_count}, "
        f"unique thread records={len(records)}, accepted={len(unique)}, "
        f"rejected_internal={rejected_internal}, rejected_weak={rejected_weak}"
    )

    if len(unique) == 0:
        sample_hrefs = []
        for anchor in soup.select("a[href]")[:35]:
            sample_hrefs.append(anchor.get("href") or "")
        log(f"Portal extraction debug: first href samples={sample_hrefs}")
    else:
        for item in unique[:8]:
            log(f"Accepted portal article: {item['title']} | {item['link']}")

    return unique

# -----------------------------
# Article detail extraction
# -----------------------------

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
        "twemoji",
        "emoji",
        "unicode/64/",
        "giphy.gif",
        "facebook.com/tr",
    ]

    bad_extensions = [
        ".gif",
        ".svg",
        ".webp",
    ]

    if any(part in low for part in bad_parts):
        return False

    if any(low.endswith(ext) for ext in bad_extensions):
        return False

    return True


def safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def get_img_src(img, base_url):
    for attr in ("data-url", "data-src", "src"):
        src = img.get(attr)
        if src:
            return normalize_url(src, base_url)
    return ""


def is_probably_too_small(img):
    width = safe_int(img.get("width"))
    height = safe_int(img.get("height"))

    if width and width < 120:
        return True
    if height and height < 120:
        return True

    return False


def score_image_candidate(url, img_tag=None):
    if not is_good_image_url(url):
        return -1000

    low = url.lower()
    score = 0

    if "/data/features/" in low:
        score += 120
    if "/ewr-porta/attachments/" in low:
        score += 90
    if "/attachments/" in low:
        score += 80
    if "/data/attachments/" in low:
        score += 75
    if low.endswith(".jpg") or low.endswith(".jpeg") or low.endswith(".png"):
        score += 20
    if ".jpg" in low or ".jpeg" in low or ".png" in low:
        score += 10

    if img_tag is not None:
        if is_probably_too_small(img_tag):
            score -= 90

        classes = " ".join(img_tag.get("class", [])) if img_tag.get("class") else ""
        alt = (img_tag.get("alt") or "").lower()
        title = (img_tag.get("title") or "").lower()

        bad_words = ["emoji", "smilie", "avatar", "reaction", "icon", "logo"]
        if any(word in classes.lower() for word in bad_words):
            score -= 120
        if any(word in alt for word in bad_words):
            score -= 120
        if any(word in title for word in bad_words):
            score -= 120

        parent = img_tag.parent
        if parent is not None:
            parent_classes = " ".join(parent.get("class", [])) if parent.get("class") else ""
            if any(word in parent_classes.lower() for word in bad_words):
                score -= 120

    return score


def get_first_message_body(soup):
    selectors = [
        "article.message:first-of-type .bbWrapper",
        "article.message--post:first-of-type .bbWrapper",
        "article.message--article:first-of-type .bbWrapper",
        ".message--article .bbWrapper",
        ".message-body .bbWrapper",
        "[itemprop='articleBody']",
        ".bbWrapper",
    ]

    for selector in selectors:
        body = soup.select_one(selector)
        if body:
            return body

    return soup


def extract_first_good_image(soup, base_url):
    candidates = []

    # 1) Prefer explicit feature/meta images when available.
    for meta_key in ("og:image", "twitter:image"):
        meta_img = get_meta_content(soup, meta_key)
        if meta_img:
            meta_img = normalize_url(meta_img, base_url)
            candidates.append((score_image_candidate(meta_img), meta_img, "meta"))

    # 2) If the feature image is missing/bad, scan the first thread message.
    first_body = get_first_message_body(soup)
    for img in first_body.select("img"):
        src = get_img_src(img, base_url)
        if not src:
            continue
        candidates.append((score_image_candidate(src, img), src, "first-message"))

    # 3) Last fallback: scan every image on the page.
    for img in soup.select("img"):
        src = get_img_src(img, base_url)
        if not src:
            continue
        candidates.append((score_image_candidate(src, img) - 20, src, "page"))

    if not candidates:
        return ""

    # Keep first occurrence for duplicate URLs, but preserve the best score.
    best_by_url = {}
    for score, url, source in candidates:
        if url not in best_by_url or score > best_by_url[url][0]:
            best_by_url[url] = (score, url, source)

    ranked = sorted(best_by_url.values(), key=lambda x: x[0], reverse=True)
    best_score, best_url, best_source = ranked[0]

    if best_score < 0:
        return ""

    log(f"Selected image from {best_source}: score={best_score} url={best_url}")
    return best_url

def extract_summary(soup):
    body = (
        soup.select_one(".message--article .bbWrapper")
        or soup.select_one(".message-body .bbWrapper")
        or soup.select_one("[itemprop='articleBody']")
        or soup.select_one(".bbWrapper")
    )

    if body:
        body = BeautifulSoup(str(body), "html.parser")
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
        log(f"Could not open article, using fallback data: {item['link']}")
        return {
            "title": clean_title(item["title"]),
            "link": item["link"],
            "image_url": "",
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
    image_url = extract_first_good_image(soup, item["link"])
    author = extract_author(soup)
    date = extract_article_date(soup)

    return {
        "title": title,
        "link": item["link"],
        "image_url": image_url,
        "image_name": "default.png",
        "author": author,
        "summary": summary,
        "date": date,
    }


# -----------------------------
# Images
# -----------------------------

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

    content = fetch_binary(image_url)
    if not content:
        return False

    try:
        img = Image.open(BytesIO(content))
        save_jpeg_versions(img, path_uncompressed, path_compressed)
        log(f"Saved image: {image_name}")
        return True
    except UnidentifiedImageError as e:
        log(f"Image error for {image_name}: cannot identify image file -> {e}")
        return False
    except Exception as e:
        log(f"Image error for {image_name}: {e}")
        return False


# -----------------------------
# Main scraping flow
# -----------------------------

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
        news = read_article_detail(item)
        news_list.append(news)
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

        image_name = safe_image_file_name(n["title"], n["link"])

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


def validate_feed_contract():
    if not os.path.exists(XML_PATH):
        log("ERROR: XML file was not created")
        raise SystemExit(1)

    with open(XML_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    material_open_count = content.count("<mtrl")
    material_close_count = content.count("</mtrl>")
    description_count = content.count("<description>")
    creator_count = content.count("<creators>")

    log(f"XML size: {len(content)} chars")
    log(f"XML material count: {material_open_count}")
    log(f"XML material close count: {material_close_count}")
    log(f"XML description count: {description_count}")
    log(f"XML creators count: {creator_count}")

    if material_open_count <= 0:
        log("ERROR: feed was created without any <mtrl> items")
        raise SystemExit(1)

    if material_open_count != material_close_count:
        log("ERROR: feed has mismatched <mtrl> open/close counts")
        raise SystemExit(1)

    if description_count != material_open_count:
        log("ERROR: feed has missing <description> entries")
        raise SystemExit(1)

    if creator_count != material_open_count:
        log("ERROR: feed has missing <creators> entries")
        raise SystemExit(1)

    if "</spc>" not in content or "</nsx>" not in content:
        log("ERROR: feed is missing closing </spc> or </nsx> tags")
        raise SystemExit(1)

    log("Feed contract validation: OK")


def update_psx_news():
    log("Starting PSX-Place Scraper v13 filtered portal links")
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
    validate_feed_contract()

    log("Success: XML and images were generated")
    log(f"XML output: {XML_PATH}")
    log(f"Uncompressed images: {DIR_UNCOMPRESSED}")
    log(f"Compressed images: {DIR_COMPRESSED}")


if __name__ == "__main__":
    update_psx_news()
