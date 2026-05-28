import os
import re
import time
import hashlib
from io import BytesIO
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from xml.sax.saxutils import escape


PSX_BASE = "https://www.psx-place.com/"
GITHUB_RAW_PREFIX = "https://raw.githubusercontent.com/PS3-Pro/PSX-Place/master/resources/images/uncompressed/"

MAX_PAGES = 20
MAX_ITEMS = 120
REQUEST_DELAY = 1.0
IMPERSONATE = "safari15_5"

DIR_FILES = "files"
DIR_UNCOMPRESSED = os.path.join("resources", "images", "uncompressed")
DIR_COMPRESSED = os.path.join("resources", "images", "compressed")


def now_stamp():
    return datetime.now().strftime("%H:%M:%S")


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def xml_escape(text):
    return escape(str(text or ""), {
        '"': "&quot;",
        "'": "&apos;"
    })


def normalize_url(href, base=PSX_BASE):
    if not href:
        return ""

    url = urljoin(base, href)
    url = url.split("#")[0]

    parsed = urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return clean


def portal_url(page):
    if page <= 1:
        return PSX_BASE

    return f"{PSX_BASE}ewr-porta/page-{page}"


def fetch_html(url, timeout=30):
    for attempt in range(1, 4):
        try:
            response = requests.get(
                url,
                impersonate=IMPERSONATE,
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": PSX_BASE,
                }
            )

            if response.status_code == 200:
                return response.text

            print(f"[{now_stamp()}] HTTP {response.status_code}: {url}")

        except Exception as e:
            print(f"[{now_stamp()}] Fetch error attempt {attempt}: {url} -> {e}")

        time.sleep(attempt)

    return ""


def is_article_url(url):
    return "/threads/" in url


def is_bad_title(text):
    if not text:
        return True

    t = clean_text(text)
    low = t.lower()

    bad_exact = {
        "next", "prev", "previous", "first", "last", "go",
        "here", "click here", "read more", "continue",
        "like", "quote", "reply", "share"
    }

    if low in bad_exact:
        return True

    if len(t) < 15:
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
    found = []

    preferred_selectors = [
        "h1 a[href*='/threads/']",
        "h2 a[href*='/threads/']",
        "h3 a[href*='/threads/']",
        ".contentRow-title a[href*='/threads/']",
        ".porta-title a[href*='/threads/']",
        ".message-title a[href*='/threads/']",
        ".structItem-title a[href*='/threads/']",
        "article a[href*='/threads/']",
    ]

    for selector in preferred_selectors:
        for a in soup.select(selector):
            href = normalize_url(a.get("href"))
            title = clean_text(a.get("title") or a.get_text(" ", strip=True))

            if not is_article_url(href):
                continue

            if is_bad_title(title):
                continue

            found.append({
                "title": title,
                "link": href,
            })

    if len(found) < 3:
        for a in soup.select("a[href*='/threads/']"):
            href = normalize_url(a.get("href"))
            title = clean_text(a.get("title") or a.get_text(" ", strip=True))

            if not is_article_url(href):
                continue

            if is_bad_title(title):
                continue

            found.append({
                "title": title,
                "link": href,
            })

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

    value = value.strip()

    try:
        value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    except Exception:
        pass

    return "1970-01-01T00:00:00.000Z"


def extract_thread_id(url):
    match = re.search(r"\.(\d+)/?$", url)
    if match:
        return match.group(1)

    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def clean_title(title):
    title = clean_text(title)
    title = title.replace("(Forum Thread)", "").strip()
    title = re.sub(r"\s*\|\s*PSX-Place\s*$", "", title).strip()
    return title


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
        "like",
        "reaction",
        "styles/",
        "blank.gif",
        "data:image",
    ]

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


def make_image_name(title, link):
    thread_id = extract_thread_id(link)

    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    safe_title = re.sub(r"\s+", "_", safe_title).strip("_")
    safe_title = safe_title[:80] or "psx_place"

    return f"{thread_id}_{safe_title}.jpg"


def download_and_process_image(image_url, image_name):
    path_uncompressed = os.path.join(DIR_UNCOMPRESSED, image_name)
    path_compressed = os.path.join(DIR_COMPRESSED, image_name)

    if os.path.exists(path_uncompressed) and os.path.exists(path_compressed):
        return True

    try:
        response = requests.get(
            image_url,
            impersonate=IMPERSONATE,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": PSX_BASE,
            }
        )

        if response.status_code != 200:
            print(f"[{now_stamp()}] Image HTTP {response.status_code}: {image_url}")
            return False

        img = Image.open(BytesIO(response.content))
        img = ImageOps.exif_transpose(img)

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        img.save(path_uncompressed, "JPEG", quality=92, optimize=True)

        img_optimized = ImageOps.fit(img, (290, 170), Image.Resampling.LANCZOS)
        img_optimized.save(path_compressed, "JPEG", quality=80, optimize=True)

        return True

    except Exception as e:
        print(f"[{now_stamp()}] Erro na imagem {image_name}: {e}")
        return False


def collect_news():
    seeds = []
    seen_links = set()

    for current_page in range(1, MAX_PAGES + 1):
        url = portal_url(current_page)
        print(f"-> Scraping Page {current_page}: {url}")

        html = fetch_html(url)

        if not html:
            print(f"[{now_stamp()}] Página vazia/falhou: {url}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        links = extract_portal_links(soup)

        print(f"   Found {len(links)} possible articles")

        if not links and current_page > 1:
            print("   No more articles, stopping.")
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

    print(f"-> Reading article details: {len(seeds)} items")

    news_list = []

    for i, item in enumerate(seeds, 1):
        print(f"   [{i}/{len(seeds)}] {item['title'][:70]}")
        news = read_article_detail(item)
        news_list.append(news)
        time.sleep(0.35)

    return news_list


def process_images(news_list):
    print(f"-> Processando {len(news_list)} imagens...")

    for n in news_list:
        if not n["image_url"]:
            n["image_name"] = "default.png"
            continue

        image_name = make_image_name(n["title"], n["link"])

        if download_and_process_image(n["image_url"], image_name):
            n["image_name"] = image_name
        else:
            n["image_name"] = "default.png"


def write_xml(news_list):
    xml_out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<nsx anno="" lt-id="131" min-sys-ver="1" rev="1093" ver="1.0">',
        '\t<spc anno="csxad=1&amp;adspace=9,10,11,12,13" id="33537" multi="o" rep="t">'
    ]

    for i, n in enumerate(news_list):
        picks_anno = ' anno="picks=1"' if i < 3 else ""
        image_url = f"{GITHUB_RAW_PREFIX}{n['image_name']}"

        description_html = f'<img src="{xml_escape(image_url)}"/>{xml_escape(n["summary"])}'

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

    with open(os.path.join(DIR_FILES, "whats_new.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(xml_out))


def update_psx_news():
    print(f"[{now_stamp()}] Starting PSX-Place Scraper v3/XenPorta fix...")

    os.makedirs(DIR_FILES, exist_ok=True)
    os.makedirs(DIR_UNCOMPRESSED, exist_ok=True)
    os.makedirs(DIR_COMPRESSED, exist_ok=True)

    news_list = collect_news()

    if not news_list:
        print("Nenhuma notícia encontrada. A estrutura da página pode ter mudado de novo.")
        return

    process_images(news_list)
    write_xml(news_list)

    print("Sucesso! XML e imagens geradas em:")
    print(f"- {os.path.join(DIR_FILES, 'whats_new.xml')}")
    print(f"- {DIR_UNCOMPRESSED}")
    print(f"- {DIR_COMPRESSED}")


if __name__ == "__main__":
    update_psx_news()