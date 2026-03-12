import os
import re
import time
from curl_cffi import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

def update_psx_news():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting PSX-Place Scraper...")
    
    GITHUB_RAW_PREFIX = "https://raw.githubusercontent.com/PS3-Pro/PSX-Place/master/resources/images/"
    
    MAX_PAGES = 3
    
    os.makedirs('files', exist_ok=True)
    os.makedirs(os.path.join('resources', 'images'), exist_ok=True)

    month_map = {
        "Jan": "1", "Feb": "2", "Mar": "3", "Apr": "4", "May": "5", "Jun": "6",
        "Jul": "7", "Aug": "8", "Sep": "9", "Oct": "10", "Nov": "11", "Dec": "12"
    }

    news_list = []
    seen_links = set()

    try:
        for current_page in range(1, MAX_PAGES + 1):
            url = "https://www.psx-place.com/" if current_page == 1 else f"https://www.psx-place.com/?page={current_page}"
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
                    
                    date_raw = article.select_one('span.dateData > a:nth-child(2)')
                    time_raw = article.select_one('span.dateData > a:last-child')
                    
                    ps3_date = ""
                    if date_raw and time_raw:
                        d_text = date_raw.get_text(strip=True).replace(",", "")
                        t_text = time_raw.get_text(strip=True).lower().replace("at ", "")
                        
                        parts = d_text.split()
                        if len(parts) >= 3:
                            m_name = parts[0][:3]
                            m_num = month_map.get(m_name, "1")
                            day = str(int(parts[1]))
                            year = parts[2]
                            
                            time_parts = re.findall(r'(\d+):(\d+)', t_text)
                            if time_parts:
                                hour = int(time_parts[0][0])
                                minute = time_parts[0][1]
                                if "pm" in t_text and hour < 12: hour += 12
                                if "am" in t_text and hour == 12: hour = 0
                                
                                ps3_date = f"{year}-{m_num}-{day}T{hour:02}:{minute}:00.000Z"

                    if not ps3_date:
                        n = datetime.now(timezone.utc)
                        ps3_date = f"{n.year}-{n.month}-{n.day}T{n.hour:02}:{n.minute:02}:00.000Z"
                    
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
                                            img_data = requests.get(img_url, impersonate="safari15_5", timeout=15).content
                                            with open(img_path, 'wb') as img_file:
                                                img_file.write(img_data)
                                        except Exception:
                                            local_img_name = "default.png"

                                dadi_desc = f'<img src="{GITHUB_RAW_PREFIX}{local_img_name}"><br><br><div style="text-align: center">{summary_text}</div><br/><br/><br/>'

                                news_list.append({
                                    "title": clean_title, 
                                    "link": full_link,
                                    "image": local_img_name,
                                    "author": author_text,
                                    "description": dadi_desc,
                                    "date": ps3_date
                                })
                                
                if current_page < MAX_PAGES:
                    time.sleep(3)
                    
            else:
                print(f"Failed to fetch page {current_page} (Status: {response.status_code})")
                break

        if news_list:
            xml_out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                       '<nsx anno="" lt-id="131" min-sys-ver="1" rev="1093" ver="1.0">',
                       '\t<spc anno="csxad=1&amp;adspace=9,10,11,12,13" id="33537" multi="o" rep="t">']

            for i, n in enumerate(news_list): 
                picks_anno = ' anno="picks=1"' if i < 3 else ''
                xml_out.append(f'\t\t<mtrl id="0" lastm="{n["date"]}" until="2100-12-31T23:59:00.000Z"{picks_anno}>')
                xml_out.append(f'\t\t\t<desc>{n["title"]}</desc>')
                xml_out.append(f'\t\t\t<url type="2">{GITHUB_RAW_PREFIX}{n["image"]}</url>')
                xml_out.append(f'\t\t\t<target type="u">{n["link"]}</target>')
                xml_out.append('\t\t\t<cntry agelmt="0">all</cntry>')
                xml_out.append('\t\t\t<lang>all</lang>')
                xml_out.append(f'\t\t\t<description>{n["description"]}</description>')
                xml_out.append(f'\t\t\t<creators>{n["author"]}</creators>')
                xml_out.append('\t\t</mtrl>')

            xml_out.append('\t</spc>')
            xml_out.append('</nsx>')

            with open("files/whats_new.xml", "w", encoding="utf-8") as f:
                f.write("\n".join(xml_out))
            print("Done! XML generated with parsed dates.")

    except Exception as e:
        print(f"Fatal Error: {e}")

if __name__ == "__main__":
    update_psx_news()