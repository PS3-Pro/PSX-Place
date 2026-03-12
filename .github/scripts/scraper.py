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
                    
                    ps3_date = ""
                    date_links = article.select('span.dateData a')
                    
                    if len(date_links) >= 3:
                        raw_date = date_links[1].get_text(strip=True).replace(",", "")
                        raw_time = date_links[2].get_text(strip=True).lower()
                        
                        try:
                            d_parts = raw_date.split()
                            m_num = month_map.get(d_parts[0][:3], "1")
                            day = str(int(d_parts[1]))
                            year = d_parts[2]
                            
                            t_match = re.search(r'(\d+):(\d+)', raw_time)
                            if t_match:
                                hh = int(t_match.group(1))
                                mm = t_match.group(2)
                                if "pm" in raw_time and hh < 12: hh += 12
                                if "am" in raw_time and hh == 12: hh = 0
                                ps3_date = f"{year}-{m_num}-{day}T{hh:02}:{mm}:00.000Z"
                        except:
                            pass

                    if not ps3_date:
                        ps3_date = "1970-01-01T00:00:00.000Z"
                    
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
                                
                                # --- NOVA LÓGICA DE NOME DE ARQUIVO ---
                                img_url = img_tag.get('src') if img_tag else ''
                                local_img_name = "default.png"
                                
                                if img_url:
                                    img_url = img_url if img_url.startswith('http') else f"https://www.psx-place.com/{img_url.lstrip('/')}"
                                    
                                    # 1. Remove caracteres inválidos para nomes de arquivos (\ / : * ? " < > |)
                                    safe_name = re.sub(r'[\\/*?:"<>|]', '', clean_title)
                                    # 2. Substitui espaços por underscores
                                    safe_name = safe_name.replace(' ', '_')
                                    # 3. Limita o tamanho para não dar erro no Windows/Linux (150 caracteres é seguro)
                                    safe_name = safe_name[:150].strip('_')
                                    
                                    local_img_name = f"{safe_name}.jpg"
                                # --------------------------------------

                                desc = f'<img src="{GITHUB_RAW_PREFIX}{local_img_name}">{summary_text}'

                                news_list.append({
                                    "title": clean_title, 
                                    "link": full_link,
                                    "image_url": img_url,
                                    "image_name": local_img_name,
                                    "author": author_text,
                                    "description": desc,
                                    "date": ps3_date
                                })
                                
                if current_page < MAX_PAGES:
                    time.sleep(3)
                    
            else:
                print(f"Failed to fetch page {current_page} (Status: {response.status_code})")
                break

        if news_list:
            print(f"-> Foram validados {len(news_list)} artigos. Baixando imagens...")
            for n in news_list:
                if n["image_url"] and n["image_name"] != "default.png":
                    img_path = os.path.join('resources', 'images', n["image_name"])
                    
                    if not os.path.exists(img_path):
                        try:
                            img_data = requests.get(n["image_url"], impersonate="safari15_5", timeout=15).content
                            with open(img_path, 'wb') as img_file:
                                img_file.write(img_data)
                        except Exception:
                            n["image_name"] = "default.png"

            xml_out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                       '<nsx anno="" lt-id="131" min-sys-ver="1" rev="1093" ver="1.0">',
                       '\t<spc anno="csxad=1&amp;adspace=9,10,11,12,13" id="33537" multi="o" rep="t">']

            for i, n in enumerate(news_list): 
                picks_anno = ' anno="picks=1"' if i < 3 else ''
                xml_out.append(f'\t\t<mtrl id="0" lastm="{n["date"]}" until="2100-12-31T23:59:00.000Z"{picks_anno}>')
                xml_out.append(f'\t\t\t<desc>{n["title"]}</desc>')
                xml_out.append(f'\t\t\t<url type="2">{GITHUB_RAW_PREFIX}{n["image_name"]}</url>')
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
            print(f"Sucesso! XML e {len(news_list)} imagens processadas.")

    except Exception as e:
        print(f"Fatal Error: {e}")

if __name__ == "__main__":
    update_psx_news()