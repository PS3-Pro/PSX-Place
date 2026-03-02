import requests
from bs4 import BeautifulSoup
import os

def get_ps3_news():
    url = "https://www.psx-place.com/forums/ps3-news.46/"
    # Simulates a real browser to avoid being blocked
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for thread titles (standard XenForo structure)
        # We try two different selectors just to be safe
        news_items = soup.select('div.structItem-title a[data-tp-primary="on"]')
        
        if not news_items:
            news_items = soup.find_all('h3', class_='title')

        if not news_items:
            print("No news found! Check if the website structure has changed.")
            return

        html_output = ""
        for item in news_items[:15]:
            title = item.get_text(strip=True)
            link = item['href']
            
            # Fix relative links
            if link.startswith('/'):
                full_link = f"https://www.psx-place.com{link}"
            elif not link.startswith('http'):
                full_link = f"https://www.psx-place.com/{link}"
            else:
                full_link = link
                
            html_output += f'<p>• <a href="{full_link}" target="_blank">{title}</a></p>\n'

        # Safety check: Only save if we actually got content
        if html_output:
            output_path = 'PSX_Place/PS3/news_page_code.html'
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_output)
            print(f"Success! {len(news_items)} news items saved.")
        else:
            print("HTML output is empty. Skipping file write.")

    except Exception as e:
        print(f"Error during scraping: {e}")

if __name__ == "__main__":
    get_ps3_news()