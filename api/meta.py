from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, requests

TOKEN   = os.environ.get("META_ACCESS_TOKEN", "")
ACCOUNT = "1417409513448597"
BASE    = "https://graph.facebook.com/v20.0"
FIELDS  = "spend,impressions,clicks,inline_link_clicks,actions,action_values,cpc,cost_per_inline_link_click,ctr,purchase_roas,cost_per_action_type,date_start,date_stop,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,reach,frequency"

def _av(lst, t):
    for x in (lst or []):
        if x.get("action_type") == t:
            return float(x.get("value", 0))
    return 0.0

def parse_row(row, level):
    spend = float(row.get("spend", 0) or 0)
    actions = row.get("actions", [])
    avals   = row.get("action_values", [])
    roas_l  = row.get("purchase_roas", [])
    cpa_l   = row.get("cost_per_action_type", [])
    purchase = _av(actions, "purchase")
    cpa = _av(cpa_l, "purchase")
    if cpa == 0 and purchase > 0:
        cpa = spend / purchase
    r = {
        "date_start": row.get("date_start",""),
        "spend": spend,
        "impressions": int(row.get("impressions",0) or 0),
        "clicks": int(row.get("clicks",0) or 0),
        "link_clicks": int(row.get("inline_link_clicks",0) or 0),
        "add_to_cart": _av(actions,"add_to_cart"),
        "purchase": purchase,
        "purchase_value": _av(avals,"purchase"),
        "cpc": float(row.get("cpc",0) or 0),
        "cplc": float(row.get("cost_per_inline_link_click",0) or 0),
        "ctr": float(row.get("ctr",0) or 0),
        "cpa": cpa,
        "roas": float(roas_l[0]["value"]) if roas_l else 0.0,
        "reach": int(row.get("reach",0) or 0),
        "frequency": float(row.get("frequency",0) or 0),
    }
    if "age"    in row: r["age"]    = row["age"]
    if "gender" in row: r["gender"] = row["gender"]
    if level in ("campaign","ad"):
        r["campaign_id"]   = row.get("campaign_id","")
        r["campaign_name"] = row.get("campaign_name","")
    if level == "ad":
        r["adset_id"]   = row.get("adset_id","")
        r["adset_name"] = row.get("adset_name","")
        r["ad_id"]      = row.get("ad_id","")
        r["ad_name"]    = row.get("ad_name","")
    return r

def fetch(since, until, level, time_inc="1", breakdowns=None):
    url = f"{BASE}/act_{ACCOUNT}/insights"
    params = {
        "access_token": TOKEN,
        "fields": FIELDS,
        "level": level,
        "time_ranges": json.dumps([{"since": since, "until": until}]),
        "time_increment": time_inc,
        "limit": 500,
    }
    if breakdowns:
        params["breakdowns"] = breakdowns
    rows = []
    while url:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        rows += [parse_row(row, level) for row in data.get("data",[])]
        url = data.get("paging",{}).get("next")
        params = {}
    return rows

def fetch_ad_urls():
    result = {}
    url = f"{BASE}/act_{ACCOUNT}/ads"
    params = {
        "access_token": TOKEN,
        "fields": "name,creative{object_story_spec,thumbnail_url,image_url}",
        "limit": 500,
    }
    while url:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            break
        for ad in data.get("data",[]):
            name = ad.get("name","")
            creative = ad.get("creative") or {}
            spec = creative.get("object_story_spec") or {}
            dest = None
            if "link_data" in spec:
                dest = spec["link_data"].get("link")
            elif "video_data" in spec:
                dest = (spec["video_data"].get("call_to_action") or {}).get("value",{}).get("link")
            thumb = creative.get("thumbnail_url") or creative.get("image_url")
            if name not in result:
                result[name] = {"url": dest if dest and "{{" not in (dest or "") else None, "thumb": thumb}
        url = data.get("paging",{}).get("next")
        params = {}
    return result

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        since = qs.get("since",[""])[0]
        until = qs.get("until",[""])[0]
        try:
            if not TOKEN:
                raise Exception("META_ACCESS_TOKEN not set")
            daily    = fetch(since, until, "account")
            campaigns = fetch(since, until, "campaign")
            ads      = fetch(since, until, "ad")
            age      = fetch(since, until, "campaign", breakdowns="age")
            gender   = fetch(since, until, "campaign", breakdowns="gender")
            try:
                ad_urls = fetch_ad_urls()
            except:
                ad_urls = {}
            body = json.dumps({
                "daily": daily,
                "campaigns": campaigns,
                "ads": ads,
                "age": age,
                "gender": gender,
                "ad_urls": ad_urls,
                "updated": until,
            }, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type","application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
