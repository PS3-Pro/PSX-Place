import os
import re
import time
from curl_cffi import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

def update_psx_news():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting PSX-Place Scraper (Strict PS3 XML Format)...")
    
    GITHUB_RAW_PREFIX = "https://raw.githubusercontent.com/PS3-Pro/PSX-Place/master/resources/images/"
    
    MAX_PAGES = 3
    
    os.makedirs('files', exist_ok=True)
    os.makedirs(os.path.join('resources', 'images'), exist_ok=True)

    news_list = []
    seen_links = set()

    try:
        for current_page in range(1, MAX_PAGES + 1):
            url = "https://www.psx-place.com/" if current_page == 1 else f"https://www.psx-place.com/page-{current_page}"
            print(f"-> Scraping Page {current_page}: {url}")
            
            response = requests.get(url, impersonate="safari15_5", timeout=30)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                articles = soup.select('div.articleItem')
                
                for article in articles:
                    headline_tag = article.select_one('div.subHeading > a')
                    link_tag = article.select_one('div.continue > a.button')
                    img_tag = article.select_one('img')
                    
                    author_tag = article.select_one('a.username')
                    summary_tag = article.select_one('div.baseHtml > div') or article.select_one('div.baseHtml')
                    
                    if headline_tag and link_tag:
                        href = link_tag.get('href', '')
                        full_title = headline_tag.get('title') or headline_tag.get_text(strip=True)
                        
                        if href and len(full_title) > 5:
                            if href not in seen_links:
                                seen_links.add(href)
                                
                                clean_title = full_title.replace("(Forum Thread)", "").replace("...", "").strip()
                                full_link = href if href.startswith('http') else f"https://www.psx-place.com/{href.lstrip('/')}"
                                
                                author_text = author_tag.get_text(strip=True) if author_tag else "PSX-Place"
                                summary_text = summary_tag.get_text(strip=True) if summary_tag else clean_title
                                
                                img_url = img_tag.get('src') if img_tag else ''
                                local_img_name = "default.png"
                                
                                if img_url:
                                    img_url = img_url if img_url.startswith('http') else f"https://www.psx-place.com/{img_url.lstrip('/')}"
                                    safe_name = re.sub(r'[^a-zA-Z0-9]', '', clean_title)[:25]
                                    local_img_name = f"{safe_name}.jpg"
                                    img_path = os.path.join('resources', 'images', local_img_name)
                                    
                                    if not os.path.exists(img_path):
                                        try:
                                            print(f"  Downloading image: {local_img_name}")
                                            img_data = requests.get(img_url, impersonate="safari15_5", timeout=15).content
                                            with open(img_path, 'wb') as img_file:
                                                img_file.write(img_data)
                                        except Exception:
                                            local_img_name = "default.png"

                                dadi_desc = f'<img src="{GITHUB_RAW_PREFIX}{local_img_name}"><br><br><div style="text-align: center">{summary_text}</div>'

                                news_list.append({
                                    "title": clean_title, 
                                    "link": full_link,
                                    "image": local_img_name,
                                    "author": author_text,
                                    "description": dadi_desc
                                })
                                
                if current_page < MAX_PAGES:
                    time.sleep(3)
                    
            else:
                print(f"Failed to fetch page {current_page} (Status: {response.status_code})")
                break

        if news_list:
            print(f"\nSuccessfully fetched {len(news_list)} articles. Generating Strict PS3 XML...")
            
            xml_out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                       '<nsx anno="" lt-id="131" min-sys-ver="1" rev="1093" ver="1.0">',
                       '\t<spc anno="csxad=1&amp;adspace=9,10,11,12,13" id="33537" multi="o" rep="t">']
            
            date_now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

            for i, n in enumerate(news_list): 
                picks_anno = ' anno="picks=1"' if i < 3 else ''
                
                xml_out.append(f'\t\t<mtrl id="0" lastm="{date_now}" until="2100-12-31T23:59:00.000Z"{picks_anno}>')
                xml_out.append(f'\t\t\t<desc>{n["title"]}</desc>')
                xml_out.append(f'\t\t\t<url type="2">{GITHUB_RAW_PREFIX}{n["image"]}</url>')
                xml_out.append(f'\t\t\t<target type="u">{n["link"]}</target>')
                
                xml_out.append('\t\t\t<cntry agelmt="0">all</cntry>')
                xml_out.append('\t\t\t<lang>all</lang>')
                
                xml_out.append(f'\t\t\t<dadi590_description><![CDATA[{n["description"]}]]></dadi590_description>')
                xml_out.append(f'\t\t\t<dadi590_creators>{n["author"]}</dadi590_creators>')
                
                xml_out.append('\t\t</mtrl>')

            xml_out.append('\t</spc>')
            xml_out.append('</nsx>')

            with open("files/whats_new.xml", "w", encoding="utf-8") as f:
                f.write("\n".join(xml_out))

            print("Done! XML is perfectly formatted for the PS3 XMB.")
        else:
            print("No articles were found across the pages.")

    except Exception as e:
        print(f"Fatal Error occurred: {e}")

if __name__ == "__main__":
    update_psx_news()