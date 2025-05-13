#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import json
import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://eurocarveiculos.com"
MAIN_LISTING_URL = "https://eurocarveiculos.com/multipla" # Main page with all vehicles

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "estoque_eurocar.json")
DYNAMIC_COOKIES_FILE = "/home/ubuntu/dynamic_cookies.json"

REQUEST_DELAY = 0.5 # Seconds of delay between detail page requests
PLAYWRIGHT_PAGE_LOAD_TIMEOUT = 90000
PLAYWRIGHT_ACTION_TIMEOUT = 15000
PLAYWRIGHT_SCROLL_TIMEOUT = 5000 # Timeout for waiting after a scroll
MAX_SCROLL_ATTEMPTS_NO_CHANGE = 3 # How many times to scroll with no height change before stopping

DETAIL_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
    "Referer": MAIN_LISTING_URL
}

def load_dynamic_cookies(cookie_file_path):
    try:
        with open(cookie_file_path, 'r', encoding='utf-8') as f:
            cookie_data = json.load(f)
            return cookie_data.get("raw_cookies", []), cookie_data.get("cookie_header_string", "")
    except Exception as e:
        print(f"Erro ao carregar cookies dinâmicos de {cookie_file_path}: {e}")
    return [], ""

def get_all_vehicles_html_with_playwright_scroll(playwright_cookies_list):
    """Usa Playwright para carregar a página principal e rolar até o fim para carregar todos os veículos."""
    full_html_content = ""
    screenshot_path_on_error = "/home/ubuntu/error_screenshot_full_scroll.png"
    if os.path.exists(screenshot_path_on_error):
        os.remove(screenshot_path_on_error)

    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=DETAIL_PAGE_HEADERS["User-Agent"],
                viewport={"width": 1366, "height": 768},
                java_script_enabled=True
            )
            if playwright_cookies_list:
                context.add_cookies(playwright_cookies_list)
                print("Cookies dinâmicos adicionados ao contexto.")

            page = context.new_page()
            print(f"Navegando para {MAIN_LISTING_URL} para carregar todos os veículos...")
            page.goto(MAIN_LISTING_URL, wait_until="networkidle", timeout=PLAYWRIGHT_PAGE_LOAD_TIMEOUT)
            print("Página principal carregada.")

            cookie_button_selector = "button:has-text(	'OK'	)" # Tab separated OK
            try:
                cookie_button = page.query_selector(cookie_button_selector)
                if cookie_button and cookie_button.is_visible():
                    print("Clicando no botão de cookies...")
                    cookie_button.click(timeout=PLAYWRIGHT_ACTION_TIMEOUT)
                    page.wait_for_timeout(2000)
            except Exception as e_cookie:
                print(f"Aviso: não foi possível clicar no botão de cookies: {e_cookie}")

            print("Iniciando processo de rolagem para carregar todos os veículos...")
            last_height = page.evaluate("document.body.scrollHeight")
            scroll_attempts_no_change = 0
            scroll_count = 0

            while scroll_attempts_no_change < MAX_SCROLL_ATTEMPTS_NO_CHANGE:
                scroll_count += 1
                print(f"Rolagem #{scroll_count}: rolando para o final da página...")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    # Esperar por um tempo ou por um evento de rede/DOM que indique carregamento
                    page.wait_for_timeout(PLAYWRIGHT_SCROLL_TIMEOUT) 
                except PlaywrightTimeoutError:
                    print("Timeout durante a espera após rolagem, continuando...")
                
                current_height = page.evaluate("document.body.scrollHeight")
                print(f"Altura anterior: {last_height}, Altura atual: {current_height}")
                if current_height == last_height:
                    scroll_attempts_no_change += 1
                    print(f"Altura da página não mudou. Tentativa {scroll_attempts_no_change}/{MAX_SCROLL_ATTEMPTS_NO_CHANGE}.")
                else:
                    scroll_attempts_no_change = 0 # Resetar contador se a altura mudou
                last_height = current_height
                
                # Opcional: verificar se um elemento "carregando mais" desapareceu ou algo similar

            print("Rolagem concluída. Acredita-se que todos os veículos foram carregados.")
            # O container principal que parece guardar os carros é 'div.bg-cinza-claro div.container div.row'
            # Dentro dele, os cards estão em 'div.col-md-9 div.row#ajax-itens-busca-multipla'
            # Vamos pegar o conteúdo de #ajax-itens-busca-multipla se existir, ou um container mais geral.
            ajax_container = page.query_selector("div#ajax-itens-busca-multipla")
            if ajax_container:
                full_html_content = ajax_container.inner_html()
                print("Conteúdo de 'div#ajax-itens-busca-multipla' extraído.")
            else:
                # Fallback para um container mais amplo se o específico não for encontrado
                # Pode ser que a estrutura mude ou o ID seja dinâmico
                broader_container = page.query_selector("body") # Último recurso, pegar o body inteiro
                if broader_container:
                    full_html_content = broader_container.inner_html()
                    print("Container 'div#ajax-itens-busca-multipla' não encontrado. Extraído HTML do body.")
                else:
                    print("Nenhum container de conteúdo principal encontrado. HTML estará vazio.")
        
        except PlaywrightTimeoutError as pte:
            print(f"Timeout do Playwright durante o carregamento/rolagem: {pte}")
            if 'page' in locals() and page:
                 page.screenshot(path=screenshot_path_on_error)
                 print(f"Screenshot de erro de Timeout salvo em {screenshot_path_on_error}.")
        except Exception as e_playwright:
            print(f"Erro geral no Playwright: {e_playwright}")
            if 'page' in locals() and page:
                 page.screenshot(path=screenshot_path_on_error)
                 print(f"Screenshot de erro geral salvo em {screenshot_path_on_error}.")
        finally:
            if browser:
                browser.close()
    return full_html_content

def extract_vehicle_details_from_detail_page(detail_url, cookie_header_str):
    current_detail_headers = DETAIL_PAGE_HEADERS.copy()
    if cookie_header_str:
        current_detail_headers["Cookie"] = cookie_header_str
    
    print(f"Acessando página de detalhes: {detail_url}")
    try:
        response = requests.get(detail_url, headers=current_detail_headers, timeout=30)
        response.raise_for_status()
        time.sleep(REQUEST_DELAY)
        soup = BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Erro ao acessar página de detalhes {detail_url}: {e}")
        return {}

    details = {
        "year": None, "km": None, "transmission": None, "doors": None,
        "color": None, "fuel": None, "description": "", "options": []
    }
    ficha_container = soup.find('h4', string=lambda text: text and 'FICHA TÉCNICA' in text.upper())
    if ficha_container:
        data_row = ficha_container.find_next_sibling('div', class_='row')
        if data_row:
            items = data_row.find_all('div', recursive=False)
            for item in items:
                label_tag = item.find('p', class_='font-size-11')
                value_tag = item.find('p', class_='font-size-13')
                if label_tag and value_tag:
                    label = label_tag.text.strip().lower()
                    value = value_tag.text.strip()
                    if 'ano' in label: details['year'] = value
                    elif 'km' in label: details['km'] = value.replace('.', '').replace('km','').strip() if value else None
                    elif 'câmbio' in label or 'cambio' in label: details['transmission'] = value
                    elif 'portas' in label: details['doors'] = value
                    elif 'cor' in label: details['color'] = value
                    elif 'combustível' in label or 'combustivel' in label: details['fuel'] = value
    description_container = soup.find('h4', string=lambda text: text and '+ INFORMAÇÕES' in text.upper())
    if description_container:
        description_div = description_container.find_next_sibling('div')
        if description_div: details['description'] = description_div.get_text(separator='\n', strip=True)
    opcionais_container = soup.find('h4', string=lambda text: text and 'OPCIONAIS' in text.upper())
    if opcionais_container:
        ul_opcionais = opcionais_container.find_next_sibling('ul', class_='list-unstyled')
        if ul_opcionais:
            for li in ul_opcionais.find_all('li'):
                details['options'].append(li.text.strip())
    return details

def scrape_eurocar_full_scroll():
    all_vehicles_data = []
    playwright_cookies, requests_cookie_header = load_dynamic_cookies(DYNAMIC_COOKIES_FILE)

    if not requests_cookie_header and not playwright_cookies:
        print("ALERTA: Cookies dinâmicos não carregados. A extração pode ter problemas.")

    print("\n--- Iniciando extração de todos os veículos via rolagem da página ---")
    full_listing_html = get_all_vehicles_html_with_playwright_scroll(playwright_cookies)
    
    if not full_listing_html:
        print("Não foi possível obter o HTML da listagem completa. Encerrando.")
        return []

    soup = BeautifulSoup(full_listing_html, 'html.parser')
    # Selector para os cards de veículo, baseado na análise anterior
    vehicle_cards_on_page = soup.find_all('div', class_="carro col-md-4 col-result-pact")
    
    if not vehicle_cards_on_page:
        # Fallback se a classe principal mudar, procurando por 'div.card' mais genérico
        vehicle_cards_on_page = soup.find_all('div', class_="card") 
        if not vehicle_cards_on_page:
                print("Nenhum card de veículo encontrado no HTML processado após rolagem completa.")
                return []
    
    print(f"Encontrados {len(vehicle_cards_on_page)} cards de veículos após rolagem completa.")

    for i, card_container in enumerate(vehicle_cards_on_page):
        print(f"Processando card {i+1}/{len(vehicle_cards_on_page)}...")
        card = card_container.find('div', class_='card') # O card real com as infos
        if not card: card = card_container # Se o container já for o card
        
        vehicle_info = {
            "name": None, "price": None, "year_listing": None, "km_listing": None,
            "link_details": None,
            "main_image_url": "https://eurocarveiculos.com/sites/eurocarveiculos.com/img/lazy.gif", # Placeholder
        }
        
        title_anchor = card.select_one('h2.tit-marca a.big-inf2')
        if title_anchor:
            vehicle_info['name'] = title_anchor.text.strip()
            detail_link_suffix = title_anchor['href']
            vehicle_info['link_details'] = f"{BASE_URL}{detail_link_suffix}" if not detail_link_suffix.startswith('http') else detail_link_suffix
        else:
            print(f"  Nome/link não encontrado no card {i+1}. Pulando card.")
            continue # Pula para o próximo card se não encontrar nome/link
        
        price_span = card.select_one('h3.preco span#valor_veic, h3.preco span#valor_promo_veic')
        if price_span:
            price_text = price_span.text.strip().replace('R$', '').replace('.', '').replace(',', '.').strip()
            try: vehicle_info['price'] = f"{float(price_text):.2f}"
            except ValueError: vehicle_info['price'] = None
        
        features_container = card.select_one('div.white-inf-rs')
        if features_container:
            year_text_node = features_container.find('span', class_='text-none grey-text10')
            if year_text_node: vehicle_info['year_listing'] = year_text_node.text.strip()
            
            # Tentar encontrar KM de forma mais robusta
            km_element = None
            possible_km_parents = features_container.find_all('span', class_='text-none grey-text10')
            for el in possible_km_parents:
                if "km" in el.text.lower() or (el.find_previous_sibling('svg') and "M12" in str(el.find_previous_sibling('svg'))): # Heurística para SVG de odômetro
                    km_element = el
                    break
            if km_element:
                vehicle_info['km_listing'] = km_element.text.replace('.', '').replace('km','').strip()
        
        if vehicle_info['link_details']:
            details_from_page = extract_vehicle_details_from_detail_page(vehicle_info['link_details'], requests_cookie_header)
            vehicle_info.update(details_from_page)
        else:
            print(f"  Link de detalhes não encontrado para o card {i+1}, não será possível buscar detalhes adicionais.")
        
        all_vehicles_data.append(vehicle_info)
        if (i+1) % 10 == 0:
            print(f"  {i+1} veículos processados no total...")

    return all_vehicles_data

if __name__ == "__main__":
    print("Iniciando scraper Eurocar com Playwright (rolagem completa) e Requests para detalhes...")
    if not os.path.exists(OUTPUT_DIR):
        try: os.makedirs(OUTPUT_DIR)
        except OSError as e: print(f"Erro ao criar diretório {OUTPUT_DIR}: {e}")

    vehicles_data = scrape_eurocar_full_scroll()
    
    if vehicles_data:
        try:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(vehicles_data, f, ensure_ascii=False, indent=4)
            print(f"\nDados salvos em {OUTPUT_FILE}")
            print(f"Total de {len(vehicles_data)} veículos extraídos.")
        except IOError as e: print(f"Erro ao salvar o arquivo {OUTPUT_FILE}: {e}")
    else:
        print("\nNenhum veículo foi extraído.")

