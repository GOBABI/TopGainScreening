"""
기존 screening_result.json + watchlist.json 으로 HTML 재생성 & Netlify 재배포
bot.py /refresh 명령어에서 호출
"""
import os, json, sys
from html_report import build_html, send_telegram_html

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
JSON_OUT       = os.path.join(BASE_DIR, 'screening_result.json')
WATCHLIST_FILE = os.path.join(BASE_DIR, 'watchlist.json')
ARCHIVE_PATH   = os.path.join(BASE_DIR, 'archive.json')

def load_archive_dates():
    if os.path.exists(ARCHIVE_PATH):
        with open(ARCHIVE_PATH) as f:
            return json.load(f).get('dates', [])
    return []

def main():
    if not os.path.exists(JSON_OUT):
        print("ERROR: screening_result.json 없음", flush=True)
        sys.exit(1)

    with open(JSON_OUT, 'r', encoding='utf-8') as f:
        data = json.load(f)

    wl = {}
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            wl = json.load(f)

    archive_dates = load_archive_dates()

    passed = data.get('passed', [])
    mkt    = data.get('market', {})

    build_html(passed, mkt, wl, archive_dates)

    # Netlify 재배포
    import hashlib, requests
    NETLIFY_TOKEN   = "nfp_UucfNMudbMuT34ysro6p3wSX84YzaFWS128e"
    NETLIFY_SITE_ID = "6de42aff-d3a4-4d20-b68a-b47bf1ec4701"
    html_path = os.path.join(BASE_DIR, 'us_market_screening_latest.html')
    with open(html_path, 'rb') as f:
        html_bytes = f.read()
    file_hash = hashlib.sha1(html_bytes).hexdigest()
    date = data.get('date', 'latest')
    files = {"/index.html": file_hash, f"/{date}.html": file_hash}

    r = requests.post(
        f"https://api.netlify.com/api/v1/sites/{NETLIFY_SITE_ID}/deploys",
        headers={"Authorization": f"Bearer {NETLIFY_TOKEN}", "Content-Type": "application/json"},
        json={"files": files}, timeout=30,
    )
    if not r.ok:
        print(f"Netlify 배포 실패: {r.status_code}", flush=True)
        sys.exit(1)

    deploy_id = r.json()["id"]
    required  = set(r.json().get("required", []))
    if file_hash in required:
        requests.put(
            f"https://api.netlify.com/api/v1/deploys/{deploy_id}/files/index.html",
            headers={"Authorization": f"Bearer {NETLIFY_TOKEN}", "Content-Type": "text/html"},
            data=html_bytes, timeout=60,
        )

    print(f"REFRESH_OK date={date} passed={len(passed)}", flush=True)

if __name__ == '__main__':
    main()
