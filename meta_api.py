import requests

BASE_URL = "https://graph.facebook.com/v20.0"
FIELDS = [
    "spend", "impressions", "clicks", "inline_link_clicks",
    "actions", "action_values", "cpc", "cost_per_inline_link_click",
    "ctr", "purchase_roas", "cost_per_action_type",
    "date_start", "date_stop",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "reach", "frequency",
]

def _av(lst, t):
    for x in (lst or []):
        if x.get("action_type") == t:
            return float(x.get("value", 0))
    return 0.0

def _parse(row, level):
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
        "date_start": row.get("date_start", ""),
        "spend": spend,
        "impressions": int(row.get("impressions", 0) or 0),
        "clicks": int(row.get("clicks", 0) or 0),
        "link_clicks": int(row.get("inline_link_clicks", 0) or 0),
        "add_to_cart": _av(actions, "add_to_cart"),
        "purchase": purchase,
        "purchase_value": _av(avals, "purchase"),
        "cpc": float(row.get("cpc", 0) or 0),
        "cplc": float(row.get("cost_per_inline_link_click", 0) or 0),
        "ctr": float(row.get("ctr", 0) or 0),
        "cpa": cpa,
        "roas": float(roas_l[0]["value"]) if roas_l else 0.0,
        "reach": int(row.get("reach", 0) or 0),
        "frequency": float(row.get("frequency", 0) or 0),
    }
    if "age"    in row: r["age"]    = row["age"]
    if "gender" in row: r["gender"] = row["gender"]
    if level in ("campaign", "ad"):
        r["campaign_id"]   = row.get("campaign_id", "")
        r["campaign_name"] = row.get("campaign_name", "")
    if level == "ad":
        r["adset_id"]   = row.get("adset_id", "")
        r["adset_name"] = row.get("adset_name", "")
        r["ad_id"]      = row.get("ad_id", "")
        r["ad_name"]    = row.get("ad_name", "")
    return r

def get_insights(account_id, since, until, level, time_increment, token, breakdowns=None):
    url = f"{BASE_URL}/act_{account_id}/insights"
    params = {
        "access_token": token,
        "fields": ",".join(FIELDS),
        "level": level,
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "limit": 500,
    }
    if time_increment != "all_days":
        params["time_increment"] = time_increment
    if breakdowns:
        params["breakdowns"] = breakdowns
    rows = []
    while url:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        for row in data.get("data", []):
            rows.append(_parse(row, level))
        url = data.get("paging", {}).get("next")
        params = {}
    return rows
