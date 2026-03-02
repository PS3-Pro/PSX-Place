import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime

def get_ps3_news():
    url = "https://www.psx-place.com/forums/ps3-news.46/"
    # Identifica o bot como um navegador real para evitar bloqueios
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    try:
        print(f"Connecting to {url}...")
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code != 200:
            print(f"Error: Status code {response.status_code}. Possible block by Cloudflare.")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Seletores atualizados para XenForo 2 (PSX-Place)
        # Tenta o seletor principal, se falhar, tenta alternativas
        news_items = soup.select('div.structItem-title a[data-tp-primary="on"]')
        
        if not news_items:
            news_items = soup.select('div.structItem-title a') # Fallback 1
            
        if not news_items:
            print("No news items found. The site structure might have changed.")
            return

        html_output = f"\n"
        count = 0
        
        for item in news_items:
            title = item.get_text(strip=True)
            link = item.get('href', '')
            
            # Filtra links inúteis (como links de páginas ou tags)
            if not link or "/threads/" not in link or "page-" in link:
                continue
                
            full_link = f"https://www.psx-place.com/{link.lstrip('/')}"
            html_output += f'<p>• <a href="{full_link}" target="_blank">{title}</a></p>\n'
            count += 1
            if count >= 15: break # Limite de 15 notícias

        if count > 0:
            # Adiciona um rodapé com a data da última atualização (útil para debug)
            html_output += f'<br><small style="color:gray;">Last updated: {datetime.now().strftime("%H:%M:%S")}</small>'
            
            output_path = 'PSX_Place/PS3/news_page_code.html'
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_output)
            print(f"Success! {count} items saved to {output_path}")
        else:
            print("Filtered items resulted in empty list. Check selectors.")

    except Exception as e:
        print(f"Scraper error: {e}")

if __name__ == "__main__":
    get_ps3_news()