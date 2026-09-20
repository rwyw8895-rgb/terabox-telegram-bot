import asyncio


# ============================================================
# Docker/Linux Setup — replaces the Colab Cell 1
# ============================================================
import os
import glob
import subprocess
import time
from playwright.async_api import async_playwright

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
PROFILE_DIR = os.path.join(DATA_DIR, "terabox_profile")
BROWSER_DOWNLOADS_DIR = os.path.join(DATA_DIR, "browser_downloads")
os.makedirs(PROFILE_DIR, exist_ok=True)
os.makedirs(BROWSER_DOWNLOADS_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "tg_data"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "tg_temp"), exist_ok=True)

# Remove stale Chromium singleton locks after a container restart.
for lock in glob.glob(os.path.join(PROFILE_DIR, "Singleton*")):
    try:
        os.unlink(lock) if os.path.islink(lock) else os.remove(lock)
    except Exception:
        pass

os.environ["DISPLAY"] = ":99"

def start_novnc():
    env = os.environ.copy()
    env["DISPLAY"] = ":99"

    subprocess.Popen(
        ["x11vnc", "-display", ":99", "-forever", "-shared",
         "-rfbport", "5900", "-localhost", "-nopw"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    subprocess.Popen(
        ["websockify", "--web", "/usr/share/novnc/", "6080", "localhost:5900"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1)
    print("🖥️ noVNC server started on localhost:6080")

def start_virtual_display():
    try:
        result = subprocess.run(
            ["xdpyinfo", "-display", ":99"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return
    except Exception:
        pass

    subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-ac"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)

    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    subprocess.Popen(
        ["fluxbox"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)

async def initialize_browser():
    global pw, browser_context, page
    start_virtual_display()
    start_novnc()

    pw = await async_playwright().start()
    browser_context = await pw.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        accept_downloads=True,
        downloads_path=BROWSER_DOWNLOADS_DIR,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--display=:99",
        ],
    )
    await browser_context.add_init_script("""
        window.close = function() {
            console.log("Prevented window.close");
        };
    """)

    page = (
        browser_context.pages[0]
        if browser_context.pages
        else await browser_context.new_page()
    )
    await page.set_viewport_size({"width": 1280, "height": 720})
    await page.goto(
        "https://www.terabox.app/",
        wait_until="domcontentloaded",
        timeout=120000,
    )
    print("🌐 Chromium/TeraBox browser initialized.")

async def shutdown_browser():
    try:
        if browser_context and not browser_context.is_closed():
            await browser_context.close()
    except Exception:
        pass
    try:
        if pw:
            await pw.stop()
    except Exception:
        pass


# ============================================================
# Cell 2 — TeraBox Downloader Engine
# ============================================================
import asyncio
import glob
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse, parse_qs, unquote
import zipfile
import requests

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpeg", ".mpg", ".3gp", ".ts", ".flv"}

# Comprehensive pattern supporting all TeraBox mirror domains & shortlinks
TERABOX_DOMAINS_PATTERN = r"(?:terabox|terashare|terafileshare|1024tera|1024-tera|tera-box|nephobox|mirrobox|mirrorbox|momerybox|tibibox|gibibox|pebibox|4funbox|dubox|bestclouddrive)"

def is_terabox_url(text):
    if bool(re.search(TERABOX_DOMAINS_PATTERN, text, re.I)):
        return True
    if bool(re.search(r"/(?:s|share/init|sharing/link)\?.*?(?:surl=|s/1)[a-zA-Z0-9_-]+|/s/1[a-zA-Z0-9_-]{10,}", text, re.I)):
        return True
    return False

def ensure_x_server():
    os.environ["DISPLAY"] = ":99"
    try:
        res = subprocess.run(["xdpyinfo", "-display", ":99"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return
    except Exception:
        pass

    print("🖥️ Starting Xvfb virtual display (:99)...")
    for proc in ["Xvfb", "fluxbox"]:
        subprocess.run(["pkill", "-9", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24", "-ac"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    subprocess.Popen(["fluxbox"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

async def ensure_browser():
    global pw, browser_context
    ensure_x_server()

    try:
        if browser_context and not browser_context.is_closed():
            while len(browser_context.pages) > 1:
                p = browser_context.pages[-1]
                try:
                    await p.close()
                except Exception:
                    break
            worker_page = await browser_context.new_page()
            await worker_page.set_viewport_size({"width": 1280, "height": 720})
            return worker_page
    except Exception:
        pass

    try:
        if browser_context and not browser_context.is_closed():
            await browser_context.close()
    except Exception:
        pass
    try:
        if pw:
            await pw.stop()
    except Exception:
        pass

    for lock in glob.glob(os.path.join(PROFILE_DIR, "Singleton*")):
        try:
            os.unlink(lock) if os.path.islink(lock) else os.remove(lock)
        except Exception:
            pass

    print("🔄 Launching Chromium with persistent anchor & close protection...")
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser_context = await pw.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        accept_downloads=True,
        downloads_path=BROWSER_DOWNLOADS_DIR,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--display=:99",
        ],
    )
    await browser_context.add_init_script('''
        window.close = function() {
            console.log("Prevented window.close");
        };
    ''')

    anchor_page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
    await anchor_page.goto("https://www.terabox.app/", wait_until="domcontentloaded", timeout=60000)

    worker_page = await browser_context.new_page()
    await worker_page.set_viewport_size({"width": 1280, "height": 720})
    return worker_page

def clean_filename(filename):
    if not filename:
        return ""
    filename = unquote(filename)
    filename = os.path.basename(filename)
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
    filename = filename.strip(" .")
    return filename

def detect_extension_from_magic_bytes(file_path):
    try:
        with open(file_path, "rb") as f:
            header = f.read(128)

        if len(header) >= 12 and header[4:8] == b"ftyp":
            brand = header[8:12]
            if brand in [b"qt  ", b"moov"]:
                return ".mov"
            return ".mp4"

        if header.startswith(b"\x1a\x45\xdf\xa3"):
            if b"webm" in header:
                return ".webm"
            return ".mkv"

        if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
            return ".avi"

        if header.startswith(b"ID3") or header[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
            return ".mp3"

        if header.startswith(b"PK\x03\x04"):
            return ".zip"
        if header.startswith(b"Rar!\x1a\x07"):
            return ".rar"
        if header.startswith(b"7z\xbc\xaf\x27\x1c"):
            return ".7z"

        if header.startswith(b"%PDF"):
            return ".pdf"
        if header.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
    except Exception:
        pass
    return None

def extract_filename_from_url(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in ["fin", "filename", "name", "fname", "file_name"]:
            if key in params and params[key]:
                cleaned = clean_filename(params[key][0])
                if cleaned:
                    return cleaned
    except Exception:
        pass
    try:
        for pattern in [r'fin=([^;&]+)', r'filename=([^;&]+)']:
            match = re.search(pattern, url, re.I)
            if match:
                cleaned = clean_filename(match.group(1).strip('"\''))
                if cleaned:
                    return cleaned
    except Exception:
        pass
    return None

def extract_filename_from_headers(headers):
    cd = headers.get("content-disposition", "")
    if cd:
        m = re.search(r"filename\*=UTF-8''([^;\s]+)", cd, re.I)
        if m:
            return clean_filename(m.group(1))
        for pattern in [r'filename="([^"]+)"', r"filename='([^']+)'", r'filename=([^;\s]+)']:
            m = re.search(pattern, cd, re.I)
            if m:
                return clean_filename(m.group(1).strip('"\''))
    return None

def download_signed_file(signed_url, target_dir, base_filename, cookies=None, referer=None):
    session = requests.Session()
    if cookies:
        parsed_target = urlparse(signed_url)
        target_domain = parsed_target.netloc
        for cookie in cookies:
            try:
                session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain"),
                    path=cookie.get("path", "/")
                )
                session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=target_domain,
                    path="/"
                )
            except Exception:
                pass

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Referer": referer or "https://www.terabox.app/",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }

    response = session.get(signed_url, headers=headers, stream=True, timeout=(30, 600))
    if response.status_code != 200:
        raise RuntimeError(f"TeraBox returned HTTP {response.status_code}")

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type or "application/json" in content_type:
        raise RuntimeError("TeraBox returned HTML/JSON instead of actual file content. Session may have expired.")

    header_name = extract_filename_from_headers(response.headers)
    final_filename = header_name or base_filename or "terabox_download"
    final_filename = clean_filename(final_filename) or "terabox_download"

    temp_output = os.path.join(target_dir, "download.tmp")
    total = 0
    with open(temp_output, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    actual_size = os.path.getsize(temp_output)
    if actual_size < 2048:
        with open(temp_output, "r", errors="ignore") as f:
            content = f.read(500)
        os.remove(temp_output)
        raise RuntimeError(
            f"TeraBox returned an invalid response ({actual_size} bytes).\n"
            f"Server response: {content.strip()}\n"
            f"👉 Please verify you are logged into TeraBox via noVNC."
        )

    _, current_ext = os.path.splitext(final_filename)
    detected_ext = detect_extension_from_magic_bytes(temp_output)

    if not current_ext:
        if detected_ext:
            final_filename = final_filename + detected_ext
        elif "video/mp4" in content_type:
            final_filename = final_filename + ".mp4"
        elif "application/zip" in content_type:
            final_filename = final_filename + ".zip"

    output_path = os.path.join(target_dir, final_filename)
    if os.path.exists(output_path):
        os.remove(output_path)
    os.rename(temp_output, output_path)

    session.close()
    return output_path, final_filename

def rescue_recent_browser_download(target_dir, base_filename, min_size=2048):
    dpath = BROWSER_DOWNLOADS_DIR
    if not os.path.exists(dpath):
        return None, None
    files = [
        os.path.join(dpath, f) for f in os.listdir(dpath)
        if not f.endswith(".crdownload") and not f.endswith(".tmp")
    ]
    if not files:
        return None, None
    latest_file = max(files, key=os.path.getmtime)
    if (time.time() - os.path.getmtime(latest_file) < 180) and os.path.getsize(latest_file) > min_size:
        detected_ext = detect_extension_from_magic_bytes(latest_file)
        _, curr_ext = os.path.splitext(base_filename)
        final_filename = base_filename
        if not curr_ext and detected_ext:
            final_filename += detected_ext
        final_filename = clean_filename(final_filename) or "terabox_download"
        dest_path = os.path.join(target_dir, final_filename)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        shutil.copy2(latest_file, dest_path)
        return dest_path, final_filename
    return None, None

async def save_downloaded_result(captured, job_dir, dom_filename, cookies, url):
    target_name = (
        captured.get("download_filename")
        or captured.get("filename")
        or dom_filename
        or "terabox_download"
    )
    stream_url = captured.get("download_url") or captured.get("url")

    saved_path = None
    saved_filename = None

    # Strategy 1: Native browser download.save_as
    if captured.get("download"):
        try:
            print("📥 Attempting native browser download saving...")
            download = captured["download"]
            sugg_name = clean_filename(download.suggested_filename) or target_name
            temp_path = os.path.join(job_dir, "download_native.tmp")
            await download.save_as(temp_path)

            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 2048:
                detected_ext = detect_extension_from_magic_bytes(temp_path)
                _, curr_ext = os.path.splitext(sugg_name)
                if not curr_ext and detected_ext:
                    sugg_name += detected_ext
                final_path = os.path.join(job_dir, sugg_name)
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(temp_path, final_path)
                saved_path = final_path
                saved_filename = sugg_name
                print(f"✅ Native browser download saved: {saved_filename}")
        except Exception as e:
            print(f"⚠️ Native download.save_as ({e}). Switching to next retrieval strategy...")

    # Strategy 2: Rescue completed file from browser downloads folder
    if not saved_path:
        rescued_path, rescued_name = rescue_recent_browser_download(job_dir, target_name)
        if rescued_path:
            print(f"✅ Rescued file from browser downloads folder: {rescued_name}")
            saved_path = rescued_path
            saved_filename = rescued_name

    # Strategy 3: Direct CDN stream fallback via requests with session cookies
    if not saved_path:
        if not stream_url:
            raise RuntimeError(
                "The download trigger occurred, but the target closed before saving completed "
                "and no direct download URL was intercepted.\n"
                "👉 Please verify you are logged into TeraBox via noVNC (Cell 1) and try again."
            )
        print(f"⚡ Streaming file directly from CDN: {stream_url[:80]}...")
        saved_path, saved_filename = download_signed_file(stream_url, job_dir, target_name, cookies, referer=url)
        print(f"✅ Direct CDN stream completed: {saved_filename}")

    return {
        "path": saved_path,
        "filename": saved_filename,
        "size": os.path.getsize(saved_path)
    }

async def download_terabox(url, job_dir):
    os.makedirs(job_dir, exist_ok=True)
    active_page = await ensure_browser()
    context = active_page.context
    captured = {}

    def request_handler(request):
        req_url = request.url
        is_api = any(part in req_url for part in [
            "/api/", "/rest/", "/share/download",
            "terabox.app/share/", "terabox.com/share/"
        ])
        if is_api:
            return

        is_cdn = any(dom in req_url for dom in [
            "terabox", "1024tera", "baidupcs", "bcebos", "teraboxcdn",
            "terashare", "nephobox", "4funbox"
        ])
        is_file_stream = ("/file/" in req_url) or ("baidupcs.com" in req_url and "file" in req_url)
        is_asset = any(req_url.endswith(ext) for ext in [".js", ".css", ".png", ".ico", ".html", ".svg", ".woff", ".woff2"])

        if is_cdn and is_file_stream and not is_asset:
            if not captured.get("url"):
                captured["url"] = req_url
                fname = extract_filename_from_url(req_url)
                if fname:
                    captured["filename"] = fname

    def download_handler(download):
        if not captured.get("download"):
            captured["download"] = download
        try:
            if download.url and download.url.startswith("http"):
                captured["download_url"] = download.url
        except Exception:
            pass
        try:
            if download.suggested_filename:
                captured["download_filename"] = clean_filename(download.suggested_filename)
        except Exception:
            pass

    context.on("request", request_handler)
    context.on("download", download_handler)

    try:
        print(f"🌐 Opening TeraBox URL: {url}")
        await active_page.goto(url, wait_until="domcontentloaded", timeout=120000)
        await active_page.wait_for_timeout(4000)

        # 1. Multi-File / Shared Folder Handling: Check for "Select All"
        select_all_selectors = [
            "text=Select All",
            "span:has-text('Select All')",
            "label:has-text('Select All')",
            ".select-all",
        ]
        has_select_all = False
        for sa_sel in select_all_selectors:
            try:
                sa_loc = active_page.locator(sa_sel)
                if await sa_loc.count() > 0 and await sa_loc.first.is_visible():
                    print(f"👉 Found 'Select All' checkbox ({sa_sel}). Selecting all files...")
                    await sa_loc.first.click(force=True)
                    await active_page.wait_for_timeout(1000)
                    has_select_all = True
                    break
            except Exception:
                pass

        if not has_select_all:
            try:
                cbs = active_page.locator("input[type='checkbox']")
                if await cbs.count() > 1:
                    print("👉 Found multiple checkboxes. Clicking header checkbox...")
                    await cbs.first.click(force=True)
                    await active_page.wait_for_timeout(1000)
                    has_select_all = True
            except Exception:
                pass

        # 2. Extract DOM candidate filename
        dom_filename = None
        for sel in [".file-name", ".filename", ".file_name", ".file-title", "h2", "h1"]:
            try:
                loc = active_page.locator(sel)
                if await loc.count() > 0:
                    cand = (await loc.first.inner_text()).strip()
                    if cand and len(cand) < 150:
                        dom_filename = clean_filename(cand)
                        break
            except Exception:
                pass

        # 3. Locate Download Button
        download_button = None
        selectors = [
            ".download-btn:visible",
            "button:has-text('Download'):visible",
            "text=Download",
            "a:has-text('Download'):visible",
            "span:has-text('Download'):visible"
        ]
        for sel in selectors:
            try:
                locator = active_page.locator(sel)
                if await locator.count() > 0:
                    download_button = locator.first
                    break
            except Exception:
                continue

        if not download_button:
            for btn in await active_page.locator("button, a").all():
                try:
                    text = (await btn.inner_text()).strip().lower()
                    if "download" in text and await btn.is_visible():
                        download_button = btn
                        break
                except Exception:
                    continue

        if not download_button:
            raise RuntimeError("Could not locate the 'Download' button on this TeraBox page. Link may be invalid or expired.")

        cookies = await context.cookies()
        await download_button.scroll_into_view_if_needed()
        print("⬇️ Clicking Download button...")
        await download_button.click(timeout=30000, force=True)

        # 4. Wait for download to trigger & handle secondary modals
        print("⏳ Waiting for browser download to trigger...")
        batch_blocked = False
        for i in range(80):
            if captured.get("download"):
                break

            if i in [4, 8]:
                modal_selectors = [
                    "button:has-text('Normal')",
                    "a:has-text('Normal')",
                    "button:has-text('Ordinary')",
                    "span:has-text('Normal')",
                    "button:has-text('Download anyway')",
                    "a:has-text('Download anyway')",
                    ".normal-download-btn",
                    ".download-normal"
                ]
                clicked_modal = False
                for m_sel in modal_selectors:
                    try:
                        m_btn = active_page.locator(m_sel)
                        if await m_btn.count() > 0 and await m_btn.first.is_visible():
                            print(f"👉 Clicking secondary modal button: {m_sel}...")
                            await m_btn.first.click(timeout=5000, force=True)
                            clicked_modal = True
                            break
                    except Exception:
                        pass

                if not clicked_modal and has_select_all and i == 8:
                    try:
                        client_prompt = active_page.locator("text='PC Client', text='PC client', text='desktop'")
                        if await client_prompt.count() > 0:
                            print("⚠️ TeraBox indicates batch download requires PC client. Switching to file-by-file mode...")
                            batch_blocked = True
                            await active_page.keyboard.press("Escape")
                            break
                    except Exception:
                        pass

            if i == 12 and captured.get("url") and not captured.get("download"):
                try:
                    print("⚡ Triggering stream download directly in browser context...")
                    await active_page.evaluate(f"window.location.href = '{captured['url']}'")
                except Exception:
                    pass

            await asyncio.sleep(0.5)

        # 5. File-By-File Fallback if batch was blocked
        if batch_blocked:
            print("🔄 Attempting individual file-by-file download...")
            for sa_sel in select_all_selectors:
                try:
                    sa_loc = active_page.locator(sa_sel)
                    if await sa_loc.count() > 0 and await sa_loc.first.is_visible():
                        await sa_loc.first.click(force=True)
                        await active_page.wait_for_timeout(500)
                        break
                except Exception:
                    pass

            cbs = await active_page.locator("input[type='checkbox']").all()
            downloaded_files = []
            if len(cbs) > 1:
                for idx, cb in enumerate(cbs[1:], start=1):
                    try:
                        print(f"👉 Selecting item #{idx} for single download...")
                        await cb.click(force=True)
                        await active_page.wait_for_timeout(500)
                        captured.clear()
                        await download_button.click(timeout=10000, force=True)
                        for _ in range(40):
                            if captured.get("download"):
                                break
                            await asyncio.sleep(0.5)

                        sub_file = await save_downloaded_result(captured, job_dir, dom_filename, cookies, url)
                        if sub_file:
                            downloaded_files.append(sub_file)
                        await cb.click(force=True)
                        await active_page.wait_for_timeout(500)
                    except Exception as single_err:
                        print(f"Note on item #{idx}: {single_err}")

            if downloaded_files:
                return downloaded_files

        if not captured.get("url") and not captured.get("download"):
            raise RuntimeError(
                "TeraBox download was not detected.\n"
                "This usually means TeraBox requires solving a CAPTCHA or logging in.\n"
                "👉 Please open the noVNC URL from Cell 1 and check the browser screen."
            )

        # 6. Retrieve file via Multi-Strategy Pipeline
        result_file = await save_downloaded_result(captured, job_dir, dom_filename, cookies, url)
        return [result_file]

    finally:
        try:
            context.remove_listener("request", request_handler)
            context.remove_listener("download", download_handler)
        except Exception:
            pass

print("✅ TeraBox Downloader Engine loaded successfully!")

# ============================================================
# Cell 3 — Telegram Bot Runner (Start / Stop)
# ============================================================
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 1. Load Credentials from environment
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN is required.")

print("✅ Telegram token loaded.")

# 2. Local Telegram Bot API Server (Unlocks 2 GB uploads)
use_local_server = False
if TELEGRAM_API_ID and TELEGRAM_API_HASH and os.path.exists("/usr/local/bin/telegram-bot-api"):
    print("⚡ Starting Local Telegram Bot API Server on port 8081...")
    subprocess.run(["pkill", "-9", "telegram-bot-api"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    os.makedirs("/app/data/tg_data", exist_ok=True)
    os.makedirs("/app/data/tg_temp", exist_ok=True)

    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/logOut", timeout=10)
    except Exception:
        pass

    subprocess.Popen([
        "/usr/local/bin/telegram-bot-api",
        f"--api-id={TELEGRAM_API_ID}",
        f"--api-hash={TELEGRAM_API_HASH}",
        "--local",
        "--http-port=8081",
        "--dir=/app/data/tg_data",
        "--temp-dir=/app/data/tg_temp"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    try:
        check_resp = requests.get(f"http://127.0.0.1:8081/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=5)
        if check_resp.status_code == 200:
            use_local_server = True
            print("🚀 Local Bot API Server active! Max upload limit: 2,000 MB (2 GB).")
        else:
            print("⚠️ Local Bot API Server returned code", check_resp.status_code, "- falling back to cloud (50 MB).")
    except Exception as e:
        print("⚠️ Could not reach Local Bot API Server, falling back to cloud (50 MB).", e)
else:
    print("ℹ️ Running in standard cloud mode (50 MB limit).")
    print("💡 Tip: Add TELEGRAM_API_ID & TELEGRAM_API_HASH to unlock 2 GB uploads!")

MAX_UPLOAD_MB = 1950.0 if use_local_server else 49.5

# 3. Telegram Handlers & Auto-Unpacker
download_lock = asyncio.Lock()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit_str = "2 GB" if use_local_server else "50 MB"
    await update.message.reply_text(
        f"👋 Send me any TeraBox share link (up to {limit_str}).\n\n"
        "🌐 Supported mirrors:\n"
        "• terabox.com, terabox.app, teraboxlink.com\n"
        "• terasharefile.com, terasharelink.com, terafileshare.com\n"
        "• 1024tera.com, 1024terabox.com\n"
        "• nephobox, mirrobox, 4funbox, dubox, and all mirrors!\n\n"
        "I will download files, unpack ZIPs, and upload videos and documents directly here!"
    )

async def send_single_file(update: Update, file_path, filename, prefix_caption=""):
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > MAX_UPLOAD_MB:
        await update.message.reply_text(
            f"⚠️ **File Exceeds Upload Limit ({MAX_UPLOAD_MB:.0f} MB)**\n\n"
            f"📄 File: `{filename}`\n"
            f"📦 Size: `{file_size_mb:.2f} MB`\n\n"
            f"This file exceeds the current upload limit. Skipping.",
            parse_mode="Markdown"
        )
        return

    _, ext = os.path.splitext(filename.lower())
    det_ext = detect_extension_from_magic_bytes(file_path)
    if not ext and det_ext:
        filename = filename + det_ext
        ext = det_ext.lower()

    is_video = ext in VIDEO_EXTENSIONS
    caption = f"{prefix_caption} `{filename}` ({file_size_mb:.1f} MB)".strip()

    with open(file_path, "rb") as f:
        if is_video:
            try:
                print(f"🎬 Sending video: {filename}")
                await update.message.reply_video(
                    video=f,
                    filename=filename,
                    supports_streaming=True,
                    caption=f"🎬 {caption}"
                )
            except Exception as vid_err:
                print(f"Video upload fallback to document: {vid_err}")
                f.seek(0)
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=f"📄 {caption}"
                )
        else:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f"📄 {caption}"
            )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not is_terabox_url(text):
        await update.message.reply_text("⚠️ Please send a valid TeraBox share link.")
        return

    match = re.search(r"https?://\S+", text)
    if not match:
        match = re.search(r"(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/\S+", text)
        if match:
            url = "https://" + match.group(0).lstrip("https://").lstrip("http://")
        else:
            await update.message.reply_text("⚠️ Could not find a link in your message.")
            return
    else:
        url = match.group(0)

    url = url.rstrip(").,]")
    status_msg = await update.message.reply_text("⏳ Processing link...\nConnecting to TeraBox...")

    async with download_lock:
        job_dir = tempfile.mkdtemp(prefix="terabox_job_")
        try:
            await status_msg.edit_text("⏳ Downloading from TeraBox...")
            results = await download_terabox(url, job_dir)
            if not isinstance(results, list):
                results = [results]

            for item_idx, res_item in enumerate(results, start=1):
                file_path = res_item["path"]
                filename = res_item["filename"]

                # CHECK IF ZIP / MULTI-FILE ARCHIVE
                is_zip = zipfile.is_zipfile(file_path) or filename.lower().endswith(".zip")

                if is_zip:
                    await status_msg.edit_text("📦 ZIP archive detected! Unpacking files...")
                    extract_dir = os.path.join(job_dir, f"unpacked_{item_idx}")
                    os.makedirs(extract_dir, exist_ok=True)

                    try:
                        with zipfile.ZipFile(file_path, "r") as zf:
                            zf.extractall(extract_dir)
                    except Exception as zip_err:
                        print(f"Zip extraction note: {zip_err}")

                    unpacked_files = []
                    for root, _, files in os.walk(extract_dir):
                        for f in files:
                            if f.startswith(".") or "__MACOSX" in root:
                                continue
                            full_p = os.path.join(root, f)
                            if os.path.isfile(full_p):
                                unpacked_files.append((full_p, f))

                    if unpacked_files:
                        total = len(unpacked_files)
                        await status_msg.edit_text(f"📤 Uploading {total} unpacked file(s) to Telegram...")
                        for idx, (p, fn) in enumerate(unpacked_files, start=1):
                            await send_single_file(update, p, fn, prefix_caption=f"[{idx}/{total}]")
                            await asyncio.sleep(1)
                        continue
                    else:
                        print("No files extracted from zip, falling back to sending zip file as-is.")

                # Single File Upload
                file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                prefix = f"[{item_idx}/{len(results)}] " if len(results) > 1 else ""
                await status_msg.edit_text(f"📤 Uploading `{filename}` ({file_size_mb:.1f} MB) to Telegram...", parse_mode="Markdown")
                await send_single_file(update, file_path, filename, prefix_caption=prefix)
                await asyncio.sleep(1)

            await status_msg.delete()

        except Exception as e:
            ss_path = os.path.join(job_dir, "browser_view.png")
            has_screenshot = False
            try:
                if 'browser_context' in globals() and browser_context and not browser_context.is_closed():
                    pages = browser_context.pages
                    if pages:
                        await pages[-1].screenshot(path=ss_path, full_page=False)
                        has_screenshot = os.path.exists(ss_path)
            except Exception:
                pass

            tip = "💡 *Tip:* Check the attached screenshot to see what TeraBox showed!" if has_screenshot else "💡 *Tip:* If TeraBox requires login or verification, open the noVNC URL from Cell 1."
            err_caption = (
                f"❌ **Download Failed**\n\n"
                f"**Error:** `{type(e).__name__}`\n"
                f"**Details:** {str(e)}\n\n"
                f"{tip}"
            )

            try:
                if has_screenshot:
                    with open(ss_path, "rb") as ss_file:
                        await update.message.reply_photo(
                            photo=ss_file,
                            caption=err_caption[:1024],
                            parse_mode="Markdown"
                        )
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                else:
                    await status_msg.edit_text(err_caption, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(err_caption)

        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

async def main():
    await initialize_browser()
    try:
        # Run the bot runner code by reproducing its initialization sequence.
        builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
        if use_local_server:
            builder = (
                builder.base_url("http://127.0.0.1:8081/bot")
                .base_file_url("http://127.0.0.1:8081/file/bot")
                .local_mode(True)
            )

        global app
        app = builder.build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

        print("🤖 Initializing Telegram bot...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        print("✅ Telegram bot is active and listening for links!")

        await asyncio.Event().wait()
    finally:
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception:
            pass
        await shutdown_browser()

if __name__ == "__main__":
    asyncio.run(main())
