from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os, json, threading, hashlib
import requests as http_requests
from urllib.parse import urlparse, parse_qs
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

def fetch_ad_urls(token):
    cached = read_cache("ad_urls")
    if cached:
        return cached.get("data", {})
    result = {}
    url = f"{BASE_URL}/act_{ACCOUNT_ID}/ads"
    params = {"access_token": token,
              "fields": "name,creative{thumbnail_url,image_url}",
              "limit": 500}
    while url:
        r = http_requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            break
        for ad in data.get("data", []):
            name = ad.get("name", "")
            creative = ad.get("creative") or {}
            thumb = creative.get("thumbnail_url") or creative.get("image_url")
            if name not in result:
                result[name] = {"thumb": thumb}
        url = data.get("paging", {}).get("next")
        params = {}
    write_cache("ad_urls", {"data": result})
    return result

def fetch_meta(s, u, token):
    daily     = get_insights(ACCOUNT_ID, s, u, "account",  "1",        token)
    campaigns = get_insights(ACCOUNT_ID, s, u, "campaign", "all_days", token)
    ads       = get_insights(ACCOUNT_ID, s, u, "ad",       "all_days", token)
    age       = get_insights(ACCOUNT_ID, s, u, "campaign", "all_days", token, "age")
    gender    = get_insights(ACCOUNT_ID, s, u, "campaign", "all_days", token, "gender")
    ad_urls   = fetch_ad_urls(token)
    return {"daily": daily, "campaigns": campaigns, "ads": ads,
            "age": age, "gender": gender, "ad_urls": ad_urls,
            "since": s, "until": u, "updated": now_str()}

def refresh():
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        return
    try:
        today = datetime.now(TZ)
        s = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        u = today.strftime("%Y-%m-%d")
        result = fetch_meta(s, u, token)
        write_cache("meta", result)
        print(f"[{now_str()}] Refreshed — {len(result['campaigns'])} campaigns, {len(result['ads'])} ads")
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

    today = datetime.now(TZ)
    s = since or (today - timedelta(days=29)).strftime("%Y-%m-%d")
    u = until or today.strftime("%Y-%m-%d")

    if not force:
        cached = read_cache("meta")
        if cached and cached.get("since") == s and cached.get("until") == u:
            return jsonify(cached)

    try:
        result = fetch_meta(s, u, token)
        # 只有預設30天範圍才覆蓋 cache，自訂區間不覆蓋
        default_s = (today - timedelta(days=29)).strftime("%Y-%m-%d")
        default_u = today.strftime("%Y-%m-%d")
        if s == default_s and u == default_u:
            write_cache("meta", result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _fetch_fresh_thumb_url(name, token):
    r = http_requests.get(
        f"{BASE_URL}/act_{ACCOUNT_ID}/ads",
        params={"access_token": token,
                "fields": "name,creative{thumbnail_url,image_url,object_story_spec}",
                "filtering": json.dumps([{"field": "name", "operator": "EQUAL", "value": name}]),
                "limit": 1},
        timeout=15
    )
    for ad in r.json().get("data", []):
        cr = ad.get("creative") or {}
        oss = cr.get("object_story_spec") or {}
        oss_pic = ((oss.get("link_data") or {}).get("picture")
                   or (oss.get("video_data") or {}).get("image_url"))
        thumb = cr.get("thumbnail_url")
        return thumb or oss_pic or cr.get("image_url")
    return None

def _resize_jpeg(img_bytes, box):
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(img_bytes))
        im.thumbnail((box, box))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return img_bytes

@app.route("/api/thumb")
def api_thumb():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "missing name"}), 400
    token = os.environ.get("META_ACCESS_TOKEN")

    thumb_dir = os.path.join(CACHE_DIR, "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)
    safe = hashlib.md5(name.encode()).hexdigest()
    cache_file = os.path.join(thumb_dir, safe + ".jpg")

    if os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            return Response(f.read(), mimetype="image/jpeg")

    # 先從 ad_urls cache 拿 URL
    cached_urls = read_cache("ad_urls")
    thumb_url = (cached_urls.get("data", {}).get(name) or {}).get("thumb") if cached_urls else None

    # cache 沒有就即時查
    if not thumb_url and token:
        thumb_url = _fetch_fresh_thumb_url(name, token)

    if thumb_url:
        try:
            resp = http_requests.get(thumb_url, timeout=15)
            if resp.status_code == 200:
                img = _resize_jpeg(resp.content, 160)
                with open(cache_file, "wb") as f:
                    f.write(img)
                return Response(img, mimetype="image/jpeg")
        except Exception:
            pass

    return jsonify({"error": "not found"}), 404

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
              "fields": "name,creative{thumbnail_url,image_url}",
              "limit": 500}
    while url:
        r = http_requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            break
        for ad in data.get("data", []):
            name = ad.get("name", "")
            creative = ad.get("creative") or {}
            thumb = creative.get("thumbnail_url") or creative.get("image_url")
            if name not in result:
                result[name] = {"thumb": thumb}
        url = data.get("paging", {}).get("next")
        params = {}
    write_cache("ad_urls", {"data": result})
    return jsonify({"data": result})

@app.route("/api/google-ads")
def api_google_ads():
    since = request.args.get("since")
    until = request.args.get("until")
    try:
        from google.ads.googleads.client import GoogleAdsClient
        config = {
            "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id":       os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret":   os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token":   os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
            "use_proto_plus":  True,
        }
        client = GoogleAdsClient.load_from_dict(config)
        ga_service = client.get_service("GoogleAdsService")
        customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"]

        date_clause = "DURING LAST_30_DAYS"
        if since and until:
            date_clause = f"BETWEEN '{since}' AND '{until}'"

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                segments.date,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date {date_clause}
              AND campaign.status = 'ENABLED'
            ORDER BY segments.date DESC
        """
        rows = []
        stream = ga_service.search_stream(customer_id=customer_id, query=query)
        for batch in stream:
            for row in batch.results:
                rows.append({
                    "campaign_id":   str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "date":          row.segments.date,
                    "impressions":   row.metrics.impressions,
                    "clicks":        row.metrics.clicks,
                    "cost":          round(row.metrics.cost_micros / 1_000_000, 2),
                    "conversions":   row.metrics.conversions,
                    "conversion_value": round(row.metrics.conversions_value, 2),
                })
        return jsonify({"data": rows, "updated": now_str()})
    except KeyError as e:
        return jsonify({"error": f"Missing env var: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
