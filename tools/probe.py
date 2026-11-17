"""One-off: check which candidate careers endpoints answer. Prints one line per candidate."""
import json, time, requests
S = requests.Session(); S.headers.update({"User-Agent": "job-alert-monitor/1.0 (personal job search)", "Accept": "application/json"})
WD = [
 ("New York Life","nyl.wd5.myworkdayjobs.com","nyl","External"),
 ("New York Life","newyorklife.wd5.myworkdayjobs.com","newyorklife","NYL"),
 ("MetLife","metlife.wd5.myworkdayjobs.com","metlife","Global-Careers"),
 ("MetLife","metlife.wd1.myworkdayjobs.com","metlife","Global-Careers"),
 ("RBC","rbc.wd3.myworkdayjobs.com","rbc","RBCGLOBAL1"),
 ("Jefferies","jefferies.wd5.myworkdayjobs.com","jefferies","External"),
 ("Verisk","verisk.wd1.myworkdayjobs.com","verisk","Verisk"),
 ("Verisk","verisk.wd5.myworkdayjobs.com","verisk","Verisk"),
 ("Centene","centene.wd5.myworkdayjobs.com","centene","Centene_External"),
 ("PIMCO","pimco.wd1.myworkdayjobs.com","pimco","pimco-careers"),
 ("Northern Trust","ntrs.wd1.myworkdayjobs.com","ntrs","northerntrust"),
 ("Northwestern Mutual","northwesternmutual.wd5.myworkdayjobs.com","northwesternmutual","CORPORATE-CAREERS"),
 ("Huntington","huntington.wd5.myworkdayjobs.com","huntington","HNBcareers"),
 ("Prudential","pru.wd5.myworkdayjobs.com","pru","Careers"),
 ("OCC","theocc.wd5.myworkdayjobs.com","theocc","OCC"),
 ("Raymond James","raymondjames.wd1.myworkdayjobs.com","raymondjames","RaymondJamesCareers"),
 ("Ally","ally.wd5.myworkdayjobs.com","ally","External"),
 ("American Family","amfam.wd1.myworkdayjobs.com","amfam","Careers"),
 ("Broadridge","broadridge.wd5.myworkdayjobs.com","broadridge","Careers"),
 ("Blackstone","blackstone.wd1.myworkdayjobs.com","blackstone","Blackstone_Careers"),
 ("Asurion","asurion.wd5.myworkdayjobs.com","asurion","Asurion_Careers"),
 ("LPL Financial","lplfinancial.wd1.myworkdayjobs.com","lplfinancial","External"),
 ("LPL Financial","lpl.wd1.myworkdayjobs.com","lpl","External"),
 ("M&T Bank","mtb.wd5.myworkdayjobs.com","mtb","MTB"),
 ("Zurich","zurichna.wd1.myworkdayjobs.com","zurichna","External"),
 ("Farmers","farmersinsurance.wd1.myworkdayjobs.com","farmersinsurance","External"),
 ("Ameriprise","ameriprise.wd5.myworkdayjobs.com","ameriprise","Ameriprise"),
 ("MUFG","mufgub.wd3.myworkdayjobs.com","mufgub","MUFG-Careers"),
 ("Evercore","evercore.wd5.myworkdayjobs.com","evercore","Evercore_Careers"),
 ("CME Group","cmegroup.wd1.myworkdayjobs.com","cmegroup","cme_careers"),
 ("Liberty Mutual","libertymutual.wd5.myworkdayjobs.com","libertymutual","External"),
 ("Synchrony","synchronyfinancial.wd5.myworkdayjobs.com","synchronyfinancial","careers"),
 ("PNC","pnc.wd5.myworkdayjobs.com","pnc","External"),
 ("Capital Group","capgroup.wd1.myworkdayjobs.com","capgroup","capitalgroupcareers"),
 ("Progressive","progressive.wd5.myworkdayjobs.com","progressive","External"),
 ("MassMutual","massmutual.wd1.myworkdayjobs.com","massmutual","MMCareers"),
 ("Travelers","travelers.wd5.myworkdayjobs.com","travelers","External"),
 ("The Hartford","thehartford.wd5.myworkdayjobs.com","thehartford","Careers_External"),
 ("T. Rowe Price","troweprice.wd5.myworkdayjobs.com","troweprice","TRowePrice"),
 ("AIG","aig.wd1.myworkdayjobs.com","aig","aig"),
 ("Remitly","remitly.wd5.myworkdayjobs.com","remitly","Remitly_Careers"),
 ("Guardian","guardianlife.wd5.myworkdayjobs.com","guardianlife","Guardian-Life-Careers"),
 ("S&P Global","spgi.wd5.myworkdayjobs.com","spgi","SPGI_Careers"),
 ("Invesco","invesco.wd1.myworkdayjobs.com","invesco","IVZ"),
 ("AllianceBernstein","abglobal.wd1.myworkdayjobs.com","abglobal","alliancebernsteincareers"),
 ("Assurant","assurant.wd1.myworkdayjobs.com","assurant","Assurant_Careers"),
 ("Fifth Third","fifththird.wd5.myworkdayjobs.com","fifththird","53careers"),
 ("Ares","aresmgmt.wd1.myworkdayjobs.com","aresmgmt","External"),
 ("BMO","bmo.wd3.myworkdayjobs.com","bmo","External"),
 ("LSEG","lseg.wd3.myworkdayjobs.com","lseg","Careers"),
 ("Regions","regions.wd5.myworkdayjobs.com","regions","Regions_Careers"),
 ("Comerica","comerica.wd5.myworkdayjobs.com","comerica","Comerica_Careers"),
 ("Manulife John Hancock","manulife.wd3.myworkdayjobs.com","manulife","MFCJH_Jobs"),
 ("TD Bank","td.wd3.myworkdayjobs.com","td","TD_Bank_Careers"),
 ("Voya","voya.wd5.myworkdayjobs.com","voya","voyacareers"),
 ("Wellington","wellington.wd5.myworkdayjobs.com","wellington","External"),
 ("Western Union","westernunion.wd5.myworkdayjobs.com","westernunion","External"),
 ("Zions","zionsbancorp.wd1.myworkdayjobs.com","zionsbancorp","Zions"),
 ("Apollo","apollo.wd5.myworkdayjobs.com","apollo","External"),
]
def wd(name, host, tenant, site):
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    for attempt in range(4):
        try:
            r = S.post(url, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "analyst"}, timeout=20)
        except Exception as e:
            print(f"WD   {name:18} ERR {type(e).__name__} {host}/{site}"); return
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1)); continue
        break
    info = ""
    if r.status_code == 200:
        try:
            j = r.json(); p = (j.get("jobPostings") or [{}])[0]
            info = f"total={j.get('total')} first={p.get('title','')[:50]!r} loc={p.get('locationsText')!r} bullet={p.get('bulletFields')} path={p.get('externalPath','')[:60]}"
        except Exception as e: info = "notjson"
    else:
        info = r.text[:120].replace("\n", " ")
    print(f"WD   {name:18} {r.status_code} {host} {tenant} {site} | {info}")
    time.sleep(1.5)
    if r.status_code != 200:   # where does the tenant's root lead?
        try:
            g = S.get(f"https://{host}/", timeout=15, allow_redirects=True, headers={"Accept": "text/html"})
            print(f"       root -> {g.status_code} {g.url[:120]}")
        except Exception as e: print(f"       root ERR {type(e).__name__}")
for row in WD: wd(*row)

def show(label, url, pick, **kw):
    try:
        r = S.get(url, timeout=25, **kw)
        out = pick(r.json()) if r.status_code == 200 else r.text[:150].replace("\n", " ")
    except Exception as e:
        out = f"ERR {type(e).__name__}: {e}"[:200]; r = None
    print(f"{label} {getattr(r,'status_code','-')} | {out}")
for b in ("chime", "affirm", "jumptrading", "upstart", "point72", "lendingclub", "marqeta", "ripple", "aqr", "towerresearchcapital", "wehrtyou", "virtu", "earnin", "optiverus", "bridgewater89", "prosper", "twosigma", "janestreet", "dimensional", "moelis"):
    show(f"GH   {b:22}", f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs",
         lambda j: f"n={len(j.get('jobs',[]))} loc={(j.get('jobs') or [{}])[0].get('location')} title={(j.get('jobs') or [{}])[0].get('title')!r}")
for b in ("ramp", "chime", "jumptrading"):
    show(f"ASH  {b:22}", f"https://api.ashbyhq.com/posting-api/job-board/{b}",
         lambda j: f"n={len(j.get('jobs',[]))} keys={sorted((j.get('jobs') or [{}])[0].keys())} sample={json.dumps({k:v for k,v in (j.get('jobs') or [{}])[0].items() if k not in ('descriptionHtml','descriptionPlain')})[:600]}")
