import requests, re, itertools
from concurrent.futures import ThreadPoolExecutor
H={"User-Agent":"job-alert-monitor/1.0 (personal job search)","Accept":"application/json","Content-Type":"application/json"}
WD={
"Salesforce":"salesforce|External_Career_Site","Adobe":"adobe|external_experienced","NVIDIA":"nvidia|NVIDIAExternalCareerSite","Intel":"intel|External",
"Dell":"dell|External","HP":"hp|ExternalCareerSite","Walmart":"walmart|WalmartExternal","Target":"target|targetcareers","Disney":"disney|disneycareer",
"Comcast":"comcast|Comcast_Careers","Boeing":"boeing|EXTERNAL_CAREERS","Accenture":"accenture|AccentureCareers","Workday":"workday|Workday",
"Wintrust":"wintrust|Wintrust","First Horizon":"firsthorizon|FHN","Synovus":"synovus|Synovus","Webster Bank":"websterbank,webster|Webster",
"East West Bank":"eastwestbank,ewbc|EWB","BOK Financial":"bokf|BOKF","Western Alliance":"westernalliancebank,wal|WAL","Flagstar":"flagstar|Flagstar",
"Sun Life":"sunlife|Experienced-Jobs,SunLife","Manulife / John Hancock":"manulife|MFCJH_Jobs","Zurich":"zurich|zurich_careers,Zurich","Allianz":"allianz|External,Allianz",
"AXA XL":"axa,axaxl|AXA_XL","Swiss Re":"swissre|SwissRe","Munich Re":"munichre|MunichRe","Marsh McLennan":"mmc|MMC","Aon":"aon|AON_US_Careers,Aon","WTW":"wtwco|Careers",
"Gallagher":"ajg|AJGCareers,AJG","Brown & Brown":"bbinsurance|BBInsurance","Capital Group":"capitalgroup|capitalgroupcareers","Dimensional":"dimensional|Dimensional",
"MFS":"mfs|MFS","Russell Investments":"russellinvestments|Russell","Guidehouse":"guidehouse|External","Booz Allen":"bah|BAH_Jobs","Gartner":"gartner|EXT",
"Nielsen":"nielsen|nielsencareers","Federal Reserve":"rb|FRS","FHLB":"fhlbny|FHLBNY","Discover":"discover|Discover","Cotality":"corelogic|ACQ","Verisk":"verisk|verisk",
"ICE Mortgage":"ice|ICE","Moody's":"moodys|Moodys_Careers","BNY":"bny|BNY","Schwab":"schwab|schwab_careers","Fannie Mae":"fanniemae|FannieMae","MetLife":"metlife|External",
"Liberty Mutual":"libertymutual|LMI","Principal":"principal|Principal_External","State Farm":"statefarm|State_Farm_Careers","Progressive":"progressive|Progressive_Careers",
"Chubb":"chubb|Chubb_External","Unum":"unum|External","Aflac":"aflac|AflacCareers","Lincoln":"lincolnfinancial|LFG_Careers","Voya":"voya|VoyaCareers",
"Equitable":"equitable|Equitable_Careers","CNA":"cna|CNA","Assurant":"assurant|AssurantCareers","Paychex":"paychex|Paychex_Careers","ADP":"adp|ADP_Careers",
"Elevance":"x|x","UnitedHealth":"x|x","Kaiser Permanente":"kp|KP","Optum":"x|x","Blue Shield CA":"blueshieldca|BSC","Highmark":"highmarkhealth|highmark",
"BCBS Michigan":"bcbsm|BCBSM","Florida Blue":"floridablue|FloridaBlue","Point32":"x|x","McKesson":"mckesson|External_Careers","Cardinal Health":"cardinalhealth|EXT",
"Cencora":"cencora,amerisourcebergen|External","Expedia":"expedia|search","Marriott":"x|x","Nike":"nike|nke","Starbucks":"starbucks|StarbucksExternal","Chevron":"chevron|jobs",
"Shell":"shell|ShellCareers","Pfizer":"pfizer|PfizerCareers","Johnson & Johnson":"jj|JJ","Merck":"msd|SearchJobs","Abbott":"abbott|abbottcareers","GE":"ge|GE_ExternalSite",
"Honeywell":"honeywell|External","3M":"3m|Search","Caterpillar":"cat|CaterpillarCareers","Deere":"johndeere|DeereJobs","Ford":"ford|FordCareers","GM":"generalmotors|Careers_GM",
"T-Mobile":"tmobile|External","Verizon":"verizon|verizon-careers","AT&T":"att|ATTGeneral","Lowe's":"lowes|LWS_External_CS","Home Depot":"homedepot|CareerDepot",
"PepsiCo":"pepsico|PepsiCoCareers","Kroger":"kroger|Kroger","Mondelez":"mdlz|External","Kraft Heinz":"heinz|KraftHeinz_Careers","Dow":"dow|ExternalCareers","Bristol Myers":"bristolmyerssquibb|BMS"}
GENERIC=["External","Careers","External_Career_Site","careers","jobs","Search","ExternalCareerSite","Global","External_Careers","en-US"]
HOSTS=[1,5,3,12,10,103,108,501]
def post(host,t,s):
    try:
        r=requests.post(f"https://{host}/wday/cxs/{t}/{s}/jobs",headers=H,json={"appliedFacets":{},"limit":20,"offset":0,"searchText":"analyst"},timeout=12)
        if r.ok and "jobPostings" in r.text: return r.json().get("total")
    except Exception: pass
def probe(item):
    name,spec=item
    tens,ex=spec.split("|")
    if tens=="x": return name,None
    for t in tens.split(","):
        sites=ex.split(",")+[t,t.upper(),t.capitalize(),f"{t}careers",f"{t.capitalize()}_Careers",f"{t.upper()}_Careers",f"{t}_careers"]+GENERIC
        sites=list(dict.fromkeys(sites))
        for n in HOSTS:
            host=f"{t}.wd{n}.myworkdayjobs.com"
            # cheap host check: a bad host/tenant usually errors fast
            try:
                r=requests.get(f"https://{host}/wday/cxs/{t}/x/jobs",headers=H,timeout=8)
                if r.status_code in (404,) and "tenant" in r.text.lower() and "not" in r.text.lower(): continue
            except Exception: continue
            for s in sites:
                tot=post(host,t,s)
                if tot is not None: return name,(host,t,s,tot)
    return name,None
with ThreadPoolExecutor(24) as ex:
    for name,res in ex.map(probe, WD.items()):
        print("WD",name,res,flush=True)
GH=["airbnb","lyft","doordash","instacart","pinterest","reddit","dropbox","roblox","datadog","mongodb","databricks","okta","twilio","squarespace","duolingo","discord","figma","asana","coursera","grubhub","etsy","wayfair","peloton","zillow","opendoor","compass","redfin","chewy","flexport","samsara","cloudflare","gitlab","hubspot","elastic","yext","appian","nerdwallet","monzo","n26","billcom","klaviyo","attentive","faire","grammarly","scaleai","anthropic","openai","sigmacomputing","fivetran","dbtlabsinc","hex","amplitude","mixpanel","braze","airtable","calendly","webflow","navan","chime","wealthsimple"]
for b in GH:
    try:
        r=requests.get(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs",timeout=15)
        j=r.json().get("jobs") if r.ok else None
        a=sum(1 for x in j if "analyst" in x["title"].lower() or "analytics" in x["title"].lower()) if j else 0
        print("GH",b,len(j) if j is not None else None,a,flush=True)
    except Exception as e: print("GH",b,"ERR")
for b in ["ramp","rippling","notion","linear","openai","snowflake","deel","cohere","perplexity","harvey","replit","vercel","supabase","retool","benchling","whatnot","mercor","decagon","sierra","clay","airwallex","wealthsimple","kalshi"]:
    try:
        r=requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{b}",timeout=15)
        j=r.json().get("jobs",[]) if r.ok else None
        a=sum(1 for x in j if "analyst" in x["title"].lower() or "analytics" in x["title"].lower()) if j else 0
        print("AS",b,len(j) if j is not None else None,a,flush=True)
    except Exception: print("AS",b,"ERR")
for b in ["spotify","palantir","netflix","wealthsimple","kraken","nielsen","shopify","atlassian","eventbrite","lendingtree"]:
    try:
        r=requests.get(f"https://api.lever.co/v0/postings/{b}?mode=json",timeout=15)
        j=r.json() if r.ok else None
        a=sum(1 for x in j if "analyst" in x["text"].lower() or "analytics" in x["text"].lower()) if j else 0
        print("LV",b,len(j) if j is not None else None,a,flush=True)
    except Exception: print("LV",b,"ERR")
