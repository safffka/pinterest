import os
import time
import zipfile
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import accounts

# ======================================================
# 🔐 CONSTANTS
# ======================================================

# ======================================================
# 1. ПРОКСИ
# ======================================================
def create_proxy_extension(proxy_host, proxy_port, proxy_user, proxy_pass, plugin_path="proxy_auth_plugin.zip"):
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy Auth",
        "permissions": [
            "proxy", "tabs", "unlimitedStorage", "storage",
            "<all_urls>", "webRequest", "webRequestBlocking"
        ],
        "background": {"scripts": ["background.js"]}
    }
    """

    background_js = f"""
    var config = {{
        mode: "fixed_servers",
        rules: {{
            singleProxy: {{
                scheme: "http",
                host: "{proxy_host}",
                port: parseInt({proxy_port})
            }},
            bypassList: ["localhost"]
        }}
    }};

    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function(){{}});

    function callbackFn(details) {{
        return {{authCredentials: {{username: "{proxy_user}", password: "{proxy_pass}"}}}};
    }}

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {{urls: ["<all_urls>"]}},
        ["blocking"]
    );
    """

    with zipfile.ZipFile(plugin_path, "w") as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)

    return plugin_path


def start_browser(account, headless=False):
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1920,1080")
    proxy = account.get("proxy")
    if proxy:
        plugin = create_proxy_extension(
            proxy_host=proxy.get("host"),
            proxy_port=proxy.get("port"),
            proxy_user=proxy.get("user"),
            proxy_pass=proxy.get("pass"),
        )
        chrome_options.add_extension(plugin)

    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
    if os.path.exists(chrome_bin):
        chrome_options.binary_location = chrome_bin

    driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    service = Service(executable_path=driver_path) if os.path.exists(driver_path) else Service()

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(120)
    driver.set_script_timeout(120)
    return driver


# ======================================================
# 2. ЛОГИН PINTEREST
# ======================================================
def login_in_popup(driver, email, password):
    wait = WebDriverWait(driver, 20)

    email_input = wait.until(EC.visibility_of_element_located(
        (By.XPATH, "//input[@id='email' or @name='id']")
    ))
    email_input.send_keys(email)

    password_input = wait.until(EC.visibility_of_element_located(
        (By.XPATH, "//input[@id='password' or @name='password']")
    ))
    password_input.send_keys(password)

    login_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//button[contains(@type,'submit')]")
    ))
    login_btn.click()

    time.sleep(4)


def wait_pin_loaded(driver, timeout=25):
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "img[src*='pinimg.com']")
        ))
        time.sleep(0.7)
        return True
    except:
        return False


# ======================================================
# 3. ФУНКЦИИ ПОИСКА ЭЛЕМЕНТОВ В DROPDOWN
# ======================================================
def find_dropdown_btn_js(driver):
    return driver.execute_script("""
        const selectors = [
            "button[data-test-id='PinBetterSaveDropdown']",
            "button[aria-haspopup='true']",
            "button[aria-label*='дос']",
            "button[aria-label*='board']",
            "button[aria-label*='Choose']"
        ];
        for (const s of selectors) {
            let el = document.querySelector(s);
            if (el) return el;
        }
        return null;
    """)


def find_search_input_js(driver):
    return driver.execute_script("""
        // 1) Новый data-test-id
        let el = document.querySelector("input[data-test-id='board-picker-search']");
        if (el) return el;

        // 2) Внутри BoardPickerSearch
        el = document.querySelector("div[data-test-id='BoardPickerSearch'] input");
        if (el) return el;

        // 3) В оверлее
        const overlays = document.querySelectorAll("body > div");
        for (const ov of overlays) {
            const inp = ov.querySelector("input[type='text']");
            if (inp) return inp;
        }

        // 4) fallback по placeholder
        const all = document.querySelectorAll("input");
        for (const i of all) {
            const ph = (i.placeholder || '').toLowerCase();
            if (ph.includes('search') || ph.includes('board')) return i;
        }

        // 5) fallback по aria-label
        for (const i of all) {
            const ar = (i.getAttribute('aria-label') || '').toLowerCase();
            if (ar.includes('search') || ar.includes('board')) return i;
        }

        return null;
    """)


def select_board_from_list(driver, board_name):
    wait = WebDriverWait(driver, 8)

    xpaths = [
        f"//*[text()='{board_name}']",
        f"//*[@role='menuitem']//*[text()='{board_name}']",
        f"//*[@data-test-id='board-item']//*[text()='{board_name}']"
    ]

    for xp in xpaths:
        try:
            item = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView(true);", item)
            time.sleep(0.4)
            item.click()
            return True
        except:
            continue

    return False


# ======================================================
# 4. СОХРАНЕНИЕ ПИНА НА ДОСКУ
# ======================================================
def save_pin_to_board(driver, pin_url, board_name):
    wait = WebDriverWait(driver, 25)

    print("\n📌 Открываем пин:", pin_url)
    driver.get(pin_url)

    if not wait_pin_loaded(driver):
        print("❌ Пин не загрузился")
        return False

    # Найти большую кнопку save (НЕ НАЖИМАЕМ)
    try:
        save_btn = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//*[@data-test-id='PinBetterSaveButton']")
        ))
        print("✔ Большая кнопка Save найдена (не нажимаем)")
    except:
        print("❌ Большая кнопка Save не найдена")
        return False

    # Открываем dropdown
    dropdown = find_dropdown_btn_js(driver)
    if not dropdown:
        print("❌ Dropdown не найден")
        return False

    driver.execute_script("arguments[0].click();", dropdown)
    print("✔ Dropdown открыт")

    time.sleep(1.2)

    # Попытка найти поле поиска
    sb = find_search_input_js(driver)

    if sb:
        try:
            driver.execute_script("arguments[0].value = '';", sb)
            sb.send_keys(board_name)
            print("🔍 Ввёл в поиск:", board_name)
            time.sleep(1.3)
        except:
            print("⚠ Ошибка при вводе в поле поиска")

        # выбрать из результатов поиска
        if select_board_from_list(driver, board_name):
            print(f"🎉 Выбрана доска через поиск: {board_name}")
            return True

    # Если поиск отсутствует → fallback
    print("⚠ Поиска нет, выбираю доску из списка…")

    if select_board_from_list(driver, board_name):
        print(f"🎉 Выбрана доска из списка: {board_name}")
        return True

    print(f"❌ Не удалось выбрать доску '{board_name}'")
    return False


# ======================================================
# 5. ИЗВЛЕЧЕНИЕ ПИНОВ ИЗ ПОИСКА
# ======================================================
def collect_pin_urls(driver, query, limit=5):
    search_query = f"\"{query}\" aesthetic outfit"
    driver.get(f"https://www.pinterest.com/search/pins/?q={search_query.replace(' ', '%20')}")
    time.sleep(4)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[href*='/pin/']"))
        )
    except TimeoutException:
        print("⚠ Пины не появились в ожидании, продолжаю")

    try:
        driver.execute_script("window.scrollTo(0,2000)")
        time.sleep(2)
    except TimeoutException:
        print("⚠ Таймаут скрипта при скролле, продолжаю")

    urls = []
    for el in driver.find_elements(By.CSS_SELECTOR, "a[href*='/pin/']"):
        href = el.get_attribute("href")
        if href and "/pin/" in href:
            urls.append(href)
            if len(urls) >= limit:
                break

    return urls


# ======================================================
# 6. DOWNLOAD
# ======================================================
def find_three_dots_button_js(driver):
    return driver.execute_script("""
        // находим path с уникальным d="M2.5 9.5..."
        const p = document.querySelector("svg path[d^='M2.5 9.5']");
        if (!p) return null;

        // поднимаемся до button
        const btn = p.closest("button");
        if (btn) return btn;

        // иногда SVG завёрнут в div внутри кнопки
        return p.closest("div")?.closest("button") || null;
    """)
def click_download_image_js(driver):
    return driver.execute_script("""
        // Ищем <span> с текстом "Скачать изображение"
        const xpath = "//span[contains(text(), 'Скачать изображение')]";
        const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        if (!el) return null;

        // поднимаемся до кликабельной кнопки
        const btn = el.closest("button") || el.closest("div[role='menuitem']") || el;
        if (!btn) return null;

        btn.click();
        return true;
    """)

def download_pin_image(driver, pin_url, out_dir, filename):
    os.makedirs(out_dir, exist_ok=True)

    # Разрешаем загрузку файлов
    driver.command_executor._commands["send_command"] = (
        "POST", "/session/$sessionId/chromium/send_command"
    )

    params = {
        "cmd": "Page.setDownloadBehavior",
        "params": {
            "behavior": "allow",
            "downloadPath": out_dir
        }
    }
    driver.execute("send_command", params)

    print("📥 Открываем пин для скачивания:", pin_url)
    driver.get(pin_url)
    time.sleep(2)

    # 1️⃣ Открываем меню ⋯
    btn = None
    for _ in range(10):
        btn = find_three_dots_button_js(driver)
        if btn:
            break
        time.sleep(0.4)

    if not btn:
        print("❌ Не нашёл кнопку ⋯")
        return None

    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", btn)
    print("✔ Меню ⋯ открыто")

    time.sleep(1.0)

    # 2️⃣ Нажимаем "Скачать изображение"
    ok = click_download_image_js(driver)
    if not ok:
        print("❌ Не удалось нажать 'Скачать изображение'")
        return None

    print("✔ Кнопка 'Скачать изображение' нажата")

    # 3️⃣ Ждём, пока файл появится
    target_file = None
    for _ in range(30):
        for file in os.listdir(out_dir):
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                target_file = os.path.join(out_dir, file)
                break
        if target_file:
            break
        time.sleep(1)

    if not target_file:
        print("❌ Файл так и не появился в:", out_dir)
        return None

    final_path = os.path.join(out_dir, f"{filename}.jpg")
    os.rename(target_file, final_path)

    print("💾 Скачано:", final_path)
    return final_path



# ======================================================
# 7. LATE API
# ======================================================
def get_pinterest_account_id(account):
    r = requests.get(
        f"{account['late_base_url']}/accounts",
        headers={"Authorization": f"Bearer {account['late_api_key']}"},
    )
    r.raise_for_status()

    for acc in r.json().get("accounts", []):
        if acc.get("platform") == "pinterest":
            return acc["_id"]

    raise RuntimeError("No Pinterest account")


def get_pinterest_boards(account, account_id):
    r = requests.get(
        f"{account['late_base_url']}/accounts/{account_id}/pinterest-boards",
        headers={"Authorization": f"Bearer {account['late_api_key']}"},
    )
    r.raise_for_status()

    boards = r.json().get("boards", [])
    print("\n🧩 Доски:")
    for b in boards:
        print(f" • {b['name']} ({b['id']})")

    return boards


# ======================================================
# 8. PIPELINE
# ======================================================
def run_bot(account, target_count=5, max_attempts=25, headless=False):
    driver = start_browser(account, headless=headless)
    driver.get("https://www.pinterest.com")
    time.sleep(3)

    try:
        login_in_popup(driver, account["email"], account["password"])
    except Exception as e:
        print(f"❌ Ошибка логина: {e}")
        driver.quit()
        raise

    try:
        acc_id = get_pinterest_account_id(account)
        boards = get_pinterest_boards(account, acc_id)
    except Exception as e:
        print(f"❌ Ошибка получения досок: {e}")
        driver.quit()
        raise

    results = {}

    for b in boards:
        name = b["name"]
        board_id = b["id"]
        print(f"\n=== ▶ Работаем с доской: {name} ({board_id}) ===")

        out_dir = f"boards/{account['alias']}/{board_id}"
        if os.path.isdir(out_dir):
            existing = [
                f for f in os.listdir(out_dir)
                if f.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            if existing:
                for name in existing:
                    os.remove(os.path.join(out_dir, name))
                print(f"🧹 Очищены старые референсы: {len(existing)}")

        try:
            pin_urls = collect_pin_urls(driver, name, limit=max_attempts)
        except Exception as e:
            print(f"❌ Ошибка поиска пинов для '{name}': {e}")
            continue
        print("Найдено пинов:", pin_urls)

        saved = []

        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "board.json"), "w", encoding="utf-8") as f:
            json.dump({"id": board_id, "name": name}, f, ensure_ascii=False, indent=2)

        success_count = 0
        for url in pin_urls:
            if success_count >= target_count:
                break

            try:
                save_pin_to_board(driver, url, name)
                img = download_pin_image(driver, url, out_dir, f"{success_count + 1}")
            except Exception as e:
                print(f"❌ Ошибка сохранения/скачивания пина: {url} ({e})")
                img = None
            if img:
                saved.append(img)
                success_count += 1

        if success_count < target_count:
            print(
                f"⚠ Недостаточно референсов для '{name}': "
                f"{success_count}/{target_count}"
            )

        results[board_id] = saved

    driver.quit()
    return results


# ======================================================
# 9. RUN
# ======================================================
if __name__ == "__main__":
    account = accounts.get_account_from_env()
    files = run_bot(account)

    print("\n🎉 ГОТОВО!")
    for board, imgs in files.items():
        print(f"\n{board}:")
        for p in imgs:
            print(" •", p)
