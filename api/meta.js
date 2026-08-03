const BASE = 'https://graph.facebook.com/v20.0';
const ACCOUNT = '1417409513448597';
const FIELDS = 'spend,impressions,clicks,inline_link_clicks,actions,action_values,cpc,cost_per_inline_link_click,ctr,purchase_roas,cost_per_action_type,date_start,date_stop,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,reach,frequency';

function av(lst, t) {
  const x = (lst || []).find(i => i.action_type === t);
  return x ? parseFloat(x.value) : 0;
}

function parseRow(row, level) {
  const spend = parseFloat(row.spend || 0);
  const purchase = av(row.actions, 'purchase');
  const cpas = (row.cost_per_action_type || []).find(i => i.action_type === 'purchase');
  let cpa = cpas ? parseFloat(cpas.value) : 0;
  if (cpa === 0 && purchase > 0) cpa = spend / purchase;
  const roas = row.purchase_roas ? parseFloat(row.purchase_roas[0].value) : 0;
  const r = {
    date_start: row.date_start || '',
    spend, roas, cpa,
    impressions: parseInt(row.impressions || 0),
    clicks: parseInt(row.clicks || 0),
    link_clicks: parseInt(row.inline_link_clicks || 0),
    add_to_cart: av(row.actions, 'add_to_cart'),
    purchase,
    purchase_value: av(row.action_values, 'purchase'),
    cpc: parseFloat(row.cpc || 0),
    cplc: parseFloat(row.cost_per_inline_link_click || 0),
    ctr: parseFloat(row.ctr || 0),
    reach: parseInt(row.reach || 0),
    frequency: parseFloat(row.frequency || 0),
  };
  if (row.age) r.age = row.age;
  if (row.gender) r.gender = row.gender;
  if (level === 'campaign' || level === 'ad') {
    r.campaign_id = row.campaign_id || '';
    r.campaign_name = row.campaign_name || '';
  }
  if (level === 'ad') {
    r.adset_id = row.adset_id || '';
    r.adset_name = row.adset_name || '';
    r.ad_id = row.ad_id || '';
    r.ad_name = row.ad_name || '';
  }
  return r;
}

async function fetchInsights(token, since, until, level, breakdowns) {
  const params = new URLSearchParams({
    access_token: token,
    fields: FIELDS,
    level,
    since,
    until,
    time_increment: '1',
    limit: '500',
  });
  if (breakdowns) params.set('breakdowns', breakdowns);

  let url = `${BASE}/act_${ACCOUNT}/insights?${params}`;
  const rows = [];
  while (url) {
    const resp = await fetch(url);
    const data = await resp.json();
    if (data.error) throw new Error(data.error.message);
    (data.data || []).forEach(row => rows.push(parseRow(row, level)));
    url = data.paging?.next || null;
  }
  return rows;
}

async function fetchAdUrls(token) {
  const result = {};
  const params = new URLSearchParams({
    access_token: token,
    fields: 'name,creative{object_story_spec,thumbnail_url,image_url}',
    limit: '500',
  });
  let url = `${BASE}/act_${ACCOUNT}/ads?${params}`;
  while (url) {
    const resp = await fetch(url);
    const data = await resp.json();
    if (data.error) break;
    for (const ad of (data.data || [])) {
      const name = ad.name || '';
      const creative = ad.creative || {};
      const spec = creative.object_story_spec || {};
      let dest = spec.link_data?.link || spec.video_data?.call_to_action?.value?.link || null;
      if (dest && dest.includes('{{')) dest = null;
      if (!(name in result)) result[name] = { url: dest, thumb: creative.thumbnail_url || creative.image_url || null };
    }
    url = data.paging?.next || null;
  }
  return result;
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(204).end();

  const token = process.env.META_ACCESS_TOKEN;
  if (!token) return res.status(500).json({ error: 'META_ACCESS_TOKEN not set' });

  const { since, until } = req.query;
  if (!since || !until) return res.status(400).json({ error: 'since and until required' });

  try {
    const [daily, campaigns, ads, age, gender] = await Promise.all([
      fetchInsights(token, since, until, 'account'),
      fetchInsights(token, since, until, 'campaign'),
      fetchInsights(token, since, until, 'ad'),
      fetchInsights(token, since, until, 'campaign', 'age'),
      fetchInsights(token, since, until, 'campaign', 'gender'),
    ]);
    let ad_urls = {};
    try { ad_urls = await fetchAdUrls(token); } catch {}
    res.status(200).json({ daily, campaigns, ads, age, gender, ad_urls, updated: until });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
