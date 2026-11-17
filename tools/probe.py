"""One-off: check which candidate careers endpoints answer. Prints one line per candidate."""
import json, time, requests
S = requests.Session(); S.headers.update({"User-Agent": "job-alert-monitor/1.0 (personal job search)", "Accept": "application/json"})
WD = [  # name, host, tenant, site
 ("Fidelity","fmr.wd1.myworkdayjobs.com","fmr","FidelityCareers"),
 ("Citi","citi.wd5.myworkdayjobs.com","citi","2"),
 ("PayPal","paypal.wd1.myworkdayjobs.com","paypal","jobs"),
 ("U.S. Bank","usbank.wd1.myworkdayjobs.com","usbank","US_Bank_Careers"),
 ("Wells Fargo","wd1.myworkdaysite.com","wf","WellsFargoJobs"),
 ("GEICO","geico.wd1.myworkdayjobs.com","geico","External"),
 ("Mastercard","mastercard.wd1.myworkdayjobs.com","mastercard","CorporateCareers"),
 ("Cigna","cigna.wd5.myworkdayjobs.com","cigna","cignacareers"),
 ("Elevance Health","elevancehealth.wd1.myworkdayjobs.com","elevancehealth","ANT"),
 ("State Street","statestreet.wd1.myworkdayjobs.com","statestreet","Global"),
 ("Truist","truist.wd1.myworkdayjobs.com","truist","Careers"),
 ("CVS Health","cvshealth.wd1.myworkdayjobs.com","cvshealth","CVS_Health_Careers"),
 ("Vanguard","vanguard.wd5.myworkdayjobs.com","vanguard","vanguard_external"),
 ("Millennium","mlp.wd5.myworkdayjobs.com","mlp","mlpcareers"),
 ("HCSC","hcsc.wd1.myworkdayjobs.com","hcsc","HCSC_External"),
 ("USAA","usaa.wd1.myworkdayjobs.com","usaa","USAAJOBSWD"),
 ("Navy Federal","nfcu.wd1.myworkdayjobs.com","nfcu","NFCUCareers"),
 ("Navy Federal","nfcu.wd5.myworkdayjobs.com","nfcu","NFCUCareers"),
 ("First Citizens","firstcitizens.wd5.myworkdayjobs.com","firstcitizens","FirstCitizens"),
 ("First Citizens","fcb.wd5.myworkdayjobs.com","fcb","FCB"),
 ("ICE","ice.wd1.myworkdayjobs.com","ice","ICE"),
 ("ICE","theice.wd1.myworkdayjobs.com","theice","ICE"),
 ("Freddie Mac","freddiemac.wd5.myworkdayjobs.com","freddiemac","External"),
 ("Barclays","barclays.wd3.myworkdayjobs.com","barclays","External_Career_Site_Barclays"),
 ("Morgan Stanley","ms.wd5.myworkdayjobs.com","ms","External"),
 ("Bank of America","ghr.wd1.myworkdayjobs.com","ghr","Lateral-US"),
 ("Charles Schwab","schwab.wd5.myworkdayjobs.com","schwab","External"),
 ("Charles Schwab","schwab.wd1.myworkdayjobs.com","schwab","External"),
 ("American Express","aexp.wd5.myworkdayjobs.com","aexp","External"),
 ("UBS","ubs.wd3.myworkdayjobs.com","ubs","External"),
 ("BNY","bnymellon.wd1.myworkdayjobs.com","bnymellon","External"),
 ("Citadel","citadel.wd1.myworkdayjobs.com","citadel","External"),
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
for b in ("stripe", "coinbase", "robinhood", "sofi", "citadel", "citadelsecurities"):
    show(f"GH   {b:18}", f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs?content=true",
         lambda j: f"n={len(j.get('jobs',[]))} keys={sorted((j.get('jobs') or [{}])[0].keys())} loc={(j.get('jobs') or [{}])[0].get('location')} title={(j.get('jobs') or [{}])[0].get('title')!r}")
show("SR   Visa list", "https://api.smartrecruiters.com/v1/companies/Visa/postings?limit=3&offset=0",
     lambda j: json.dumps(j)[:1800])
try:
    pid = S.get("https://api.smartrecruiters.com/v1/companies/Visa/postings?limit=1", timeout=20).json()["content"][0]["id"]
    show("SR   Visa detail", f"https://api.smartrecruiters.com/v1/companies/Visa/postings/{pid}",
         lambda j: f"keys={sorted(j.keys())} applyUrl={j.get('applyUrl')} postingUrl={j.get('postingUrl')} sections={list((j.get('jobAd') or {}).get('sections',{}).keys())} loc={j.get('location')} exp={j.get('experienceLevel')}")
except Exception as e: print("SR detail ERR", e)
for dom, host in (("aexp.com", "aexp.eightfold.ai"), ("morganstanley.com", "morganstanley.eightfold.ai")):
    show(f"EF   {host}", f"https://{host}/api/apply/v2/jobs?domain={dom}&start=0&num=3&sort_by=timestamp&query=analyst",
         lambda j: f"count={j.get('count')} keys={sorted((j.get('positions') or [{}])[0].keys())} sample={json.dumps((j.get('positions') or [{}])[0])[:900]}")
