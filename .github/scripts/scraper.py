import requests
from bs4 import BeautifulSoup
import os

def get_ps3_news():
    url = "https://www.psx-place.com/forums/ps3-news.46/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news_items = soup.find_all('h3', class_='title')
        
        html_output = ""
        for item in news_items[:15]:
            link_tag = item.find('a')
            if link_tag:
                title = link_tag.text.strip()
                link = "https://www.psx-place.com/" + link_tag['href']
                html_output += f'<p>• <a href="{link}" target="_blank">{title}</a></p>\n'

        os.makedirs('PSX_Place/PS3', exist_ok=True)
        
        with open('PSX_Place/PS3/news_page_code.html', 'w', encoding='utf-8') as f:
            f.write(html_output)
            
        print("Notícias atualizadas com sucesso!")

    except Exception as e:
        print(f"Erro ao buscar notícias: {e}")

if __name__ == "__main__":
    get_ps3_news()