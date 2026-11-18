import requests, json, re, sys
H={"User-Agent":"job-alert-monitor/1.0 (personal job search)","Accept":"application/json"}
WD = {  # name: tenant (sites guessed via root redirect; extra site guesses after |)
 "T. Rowe Price":"troweprice|TRowePrice", "Nationwide":"nationwide|Nationwide_Career", "Allstate":"allstate|allstate_careers",
 "Travelers":"travelers|External", "Liberty Mutual":"libertymutual|LMI", "MetLife":"metlife|MetLifeCareers",
 "Humana":"humana|Humana_External_Career_Site", "KeyBank":"key|External_Career_Site", "Citizens":"citizensbank|citizens_ext",
 "Fifth Third":"fifththird|53", "Huntington":"huntington|HNBcareers", "Regions":"regions|Regions_Careers",
 "Ally":"ally|Ally_Careers", "BNY":"bnymellon|BNY_Careers", "Moody's":"moodys|Moodys", "S&P Global":"spgi|SPGI_Careers",
 "MSCI":"msci|MSCI_Careers", "ICE":"ice|ICE", "Nasdaq":"nasdaq|Global_External_Site", "Fannie Mae":"fanniemae|FannieMaeJobs",
 "TIAA":"tiaa|Search", "Principal":"principal|Principal", "Lincoln Financial":"lnc|LNC", "Equifax":"equifax|External",
 "TransUnion":"transunion|TransUnion", "Fiserv":"fiserv|EXT", "FIS":"fis|SearchJobs", "Global Payments":"tsys|TSYS",
 "Invesco":"invesco|IVZ", "Franklin Templeton":"franklintempleton|Primary-External-1", "AIG":"aig|aig",
 "Guardian Life":"glic|Guardian", "New York Life":"newyorklife|NYLCareers", "Wellington":"wellington|External",
 "Charles Schwab":"schwab|Schwab", "Chubb":"chubb|ChubbCareers", "Progressive":"progressive|Progressive",
 "Discover":"discover|Discover", "Experian":"experian|Experian", "Voya":"voya|VoyaJobs", "Edward Jones":"edwardjones|Edward_Jones_Careers",
 "Jackson Financial":"jackson|Jackson", "Comerica":"comerica|External", "Santander US":"santander|SantanderUS",
 "HSBC US":"hsbc|external", "Bloomberg":"bloomberg|Bloomberg", "Intuit":"intuit|Intuit",
}
GH=["twosigma","point72","drweng","wehrtyou","imc","brex","marqeta","mercury","citadel","hudsonrivertrading","virtu","sig","oldmission","akunacapital","optiver","flowtraders","nubank","carta","betterment","wealthfront"]
LV=["plaid","ramp","figure","addepar","ripple"]
AS=["ramp","plaid","mercury","notion"]
out=[]
def wd_try(host,tenant,site):
    try:
        r=requests.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",headers=H,json={"appliedFacets":{},"limit":20,"offset":0,"searchText":"analyst"},timeout=15)
        if r.ok: return r.json().get("total")
    except Exception: pass
    return None
for name,spec in WD.items():
    tenant,guess=spec.split("|"); found=None
    for n in (1,5,3,12,10,103,501):
        host=f"{tenant}.wd{n}.myworkdayjobs.com"
        sites=[]
        try:
            r=requests.get(f"https://{host}/",headers={"User-Agent":H["User-Agent"]},timeout=10,allow_redirects=True)
            m=re.search(r"myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)",r.url)
            if m and m.group(1) not in ("wday",""): sites.append(m.group(1))
            if r.status_code>=500 and not sites: pass
        except Exception: continue
        sites.append(guess)
        for s in dict.fromkeys(sites):
            t=wd_try(host,tenant,s)
            if t is not None: found=(host,s,t); break
        if found: break
    out.append(("workday",name,found)); print("WD",name,found,flush=True)
for b in GH:
    try:
        r=requests.get(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs",timeout=15)
        j=r.json().get("jobs") if r.ok else None
        n=len(j) if j is not None else None
        a=sum(1 for x in j if "analyst" in x["title"].lower()) if j else 0
        print("GH",b,n,a,flush=True)
    except Exception as e: print("GH",b,"ERR",e)
for b in LV:
    try:
        r=requests.get(f"https://api.lever.co/v0/postings/{b}?mode=json",timeout=15)
        print("LV",b,len(r.json()) if r.ok else r.status_code,flush=True)
    except Exception as e: print("LV",b,"ERR",e)
for b in AS:
    try:
        r=requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{b}",timeout=15)
        print("AS",b,len(r.json().get("jobs",[])) if r.ok else r.status_code,flush=True)
    except Exception as e: print("AS",b,"ERR",e)
