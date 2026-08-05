from flask import Flask, request, jsonify
from flask_cors import CORS
import os, json, threading
import requests as http_requests
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from meta_api import get_insights, BASE_URL

app = Flask(__name__)
CORS(app)

ACCOUNT_ID = "1417409513448597"
TZ = timezone(timedelta(hours=8))
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

def cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.json")

def read_cache(key):
    p = cache_path(key)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None

def write_cache(key, data):
    with open(cache_path(key), "w") as f:
        json.dump(data, f, ensure_ascii=False)

def refresh():
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        return
    try:
        today = datetime.now(TZ)
        since = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        until = today.strftime("%Y-%m-%d")
        daily     = get_insights(ACCOUNT_ID, since, until, "account",  "1",        token)
        campaigns = get_insights(ACCOUNT_ID, since, until, "campaign", "all_days", token)
        ads       = get_insights(ACCOUNT_ID, since, until, "ad",       "all_days", token)
        age       = get_insights(ACCOUNT_ID, since, until, "campaign", "all_days", token, "age")
        gender    = get_insights(ACCOUNT_ID, since, until, "campaign", "all_days", token, "gender")
        write_cache("meta", {"daily": daily, "campaigns": campaigns, "ads": ads,
                             "age": age, "gender": gender, "updated": now_str()})
        print(f"[{now_str()}] Refreshed — {len(campaigns)} campaigns, {len(ads)} ads")
    except Exception as e:
        print(f"[{now_str()}] Refresh failed: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(refresh, "cron", minute=0)
    scheduler.start()

@app.route("/api/meta")
def api_meta():
    since = request.args.get("since")
    until = request.args.get("until")
    force = request.args.get("force", "false").lower() == "true"
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        return jsonify({"error": "META_ACCESS_TOKEN not set"}), 500

    if not force:
        cached = read_cache("meta")
        if cached:
            return jsonify(cached)

    try:
        today = datetime.now(TZ)
        s = since or (today - timedelta(days=29)).strftime("%Y-%m-%d")
        u = until or today.strftime("%Y-%m-%d")
        daily     = get_insights(ACCOUNT_ID, s, u, "account",  "1",        token)
        campaigns = get_insights(ACCOUNT_ID, s, u, "campaign", "all_days", token)
        ads       = get_insights(ACCOUNT_ID, s, u, "ad",       "all_days", token)
        age       = get_insights(ACCOUNT_ID, s, u, "campaign", "all_days", token, "age")
        gender    = get_insights(ACCOUNT_ID, s, u, "campaign", "all_days", token, "gender")
        result = {"daily": daily, "campaigns": campaigns, "ads": ads,
                  "age": age, "gender": gender, "updated": now_str()}
        write_cache("meta", result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ad_urls")
def api_ad_urls():
    force = request.args.get("force", "false").lower() == "true"
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        return jsonify({"error": "META_ACCESS_TOKEN not set"}), 500
    if not force:
        cached = read_cache("ad_urls")
        if cached:
            return jsonify({"data": cached["data"]})
    result = {}
    url = f"{BASE_URL}/act_{ACCOUNT_ID}/ads"
    params = {"access_token": token,
              "fields": "name,creative{object_story_spec,thumbnail_url,image_url}",
              "limit": 500}
    while url:
        r = http_requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            break
        for ad in data.get("data", []):
            name = ad.get("name", "")
            creative = ad.get("creative") or {}
            spec = creative.get("object_story_spec") or {}
            dest = spec.get("link_data", {}).get("link") or \
                   (spec.get("video_data", {}).get("call_to_action") or {}).get("value", {}).get("link")
            if dest and "{{" in dest:
                dest = None
            thumb = creative.get("thumbnail_url") or creative.get("image_url")
            if name not in result:
                result[name] = {"url": dest, "thumb": thumb}
        url = data.get("paging", {}).get("next")
        params = {}
    write_cache("ad_urls", {"data": result})
    return jsonify({"data": result})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": now_str()})

if __name__ == "__main__":
    start_scheduler()
    threading.Thread(target=refresh, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
else:
    start_scheduler()
    threading.Thread(target=refresh, daemon=True).start()
