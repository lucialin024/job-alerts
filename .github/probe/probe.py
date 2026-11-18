import requests, re, itertools
from concurrent.futures import ThreadPoolExecutor
H={"User-Agent":"job-alert-monitor/1.0 (personal job search)","Accept":"application/json","Content-Type":"application/json"}
WD={ # name: tenants (comma) | extra sites (comma)
"KeyBank":"keybank,key|Key_Careers,External_Career_Site","Fifth Third":"fifththird,53|53,Fifth_Third_Careers","Citizens":"citizens,citizensbank|citizens_ext,CFG",
"BNY":"bnymellon,bny|BNY_Careers,bnymellon","Fannie Mae":"fanniemae|FannieMaeJobs,FannieMae","MetLife":"metlife|MetLifeCareers,MetLife",
"Liberty Mutual":"libertymutual,lmig|LMI,LibertyMutual","Ally":"ally|Ally_Careers,Ally","Moody's":"moodys|Moodys,MoodysCareers",
"MSCI":"msci|MSCI_Careers,MSCI","ICE":"intercontinentalexchange,ice,theice|ICE,ICE_Careers","Principal":"principal|Principal,Principal_Careers",
"Lincoln Financial":"lfg,lincolnfinancial|LNC,LFG","Guardian Life":"guardianlife,glic|Guardian,Guardian_Careers","New York Life":"newyorklife,nyl|NYLCareers,NYL",
"Charles Schwab":"schwab|Schwab,SchwabJobs","Chubb":"chubb|ChubbCareers,Chubb","Voya":"voya|VoyaJobs,Voya","Jackson Financial":"jackson,jacksonnational|Jackson",
"Comerica":"comerica|External,Comerica","Santander US":"santander,santanderus|SantanderUS,Santander","HSBC":"hsbc|external,HSBC","Experian":"experian|Experian,ExperianCareers",
"Intuit":"intuit|Intuit,IntuitCareers","American Express":"aexp,americanexpress|AmexCareers","Zions":"zionsbancorporation,zions|Zions","First Citizens":"firstcitizens,fcb|FCB,First_Citizens",
"BMO":"bmo|External,BMO","TD":"td,tdbank|TD_Bank_Careers","Scotiabank":"scotiabank|Scotiabank","Nomura":"nomura|Nomura,NomuraCampus","Mizuho":"mizuho,mizuhogroup|mizuhoamericas,Mizuho",
"SMBC":"smbcgroup,smbc|SMBC,SMBCGroup","BNP Paribas":"bnpparibas|BNPP","Societe Generale":"socgen,societegenerale|SG","Jefferies":"jefferies|JefferiesCareers,Jefferies",
"Lazard":"lazard|Lazard","Evercore":"evercore|Evercore","Houlihan Lokey":"hl,houlihanlokey|Campus,HL","Stifel":"stifel|Stifel","KKR":"kkr|KKR","Carlyle":"carlyle|Carlyle",
"Ares":"aresmgmt,ares|External","AllianceBernstein":"alliancebernstein,ab|AllianceBernstein","Neuberger Berman":"nb,neubergerberman|NBCareers","Federated Hermes":"federatedhermes|FederatedHermes",
"Janus Henderson":"janushenderson,jhi|JHI","Unum":"unum|Unum","Aflac":"aflac|Aflac","The Hartford":"thehartford,hartford|Careers_External","Markel":"markel|Markel",
"Molina":"molinahealthcare|Molina,MolinaHealthcare","Western Union":"westernunion,wu|WU","SS&C":"ssctech,ssc|SSCTechnologies","Envestnet":"envestnet|Envestnet",
"Morningstar":"morningstar|Americas,Morningstar","FactSet":"factset|FactSetCareers","Dun & Bradstreet":"dnb|DNB","Cboe":"cboe|External_Career_CBOE,Cboe","LSEG":"lseg|Careers",
"Navy Federal":"navyfederal|Navy_Federal_Careers","Apollo":"apollo,athene|Apollo_Careers","Discover":"discover|Discover","Schwab2":"aboutschwab|Schwab",
"Elevance2":"x|x","Raymond":"x|x","Ameritas":"ameritas|Ameritas","Thrivent":"thrivent|Thrivent","Pacific Life":"pacificlife|PacificLife","Mutual of Omaha":"mutualofomaha|MOO",
"Principal2":"principalfinancialgroup|Principal","Sallie Mae":"salliemae|SallieMae","Navient":"navient|Navient","Discover2":"x|x","Bread Financial":"breadfinancial|External",
"Equitable":"equitable|Equitable","Brighthouse":"brighthousefinancial,brighthouse|Brighthouse","Globe Life":"globelife|GlobeLife","CNA":"cna|CNA_Careers",
"W. R. Berkley":"wrberkley|WRB","Arch Capital":"archcapital,arch|Arch","Assurant":"assurant|Assurant","Kemper":"kemper|Kemper","Fidelity National Financial":"fnf|FNF",
"First American":"firstam,firstamerican|FAF","Rocket":"rocket,rocketcompanies|Rocket","Mr. Cooper":"mrcooper|MrCooper","Jack Henry":"jackhenry|JHA","Paychex":"paychex|Paychex",
"ADP":"adp|ADP","Intercontinental2":"x|x","Deloitte":"x|x","Visa":"visa|Visa","Discover3":"x|x"}
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
GH=["schonfeld","balyasny","towerresearchcapital","aqr","squarepoint","nerdwallet","upstart","toast","gusto","lendingclub","oportun","blend","pagaya","varo","greenlight","mx","alloy","moderntreasury","publicdotcom","stash","acorns","apexfintechsolutions","clearstreet","virtu","mercury","sofi","navan","bilt","imprint","sezzle","dave","wise","marqeta","checkr","addepar","ondeck","kabbage","current","valon","propel","column","arcadia","sigtech","vatic","cubist","geneva","tradeweb","marketaxess","flowdesk"]
for b in GH:
    try:
        r=requests.get(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs",timeout=15)
        j=r.json().get("jobs") if r.ok else None
        a=sum(1 for x in j if "analyst" in x["title"].lower() or "analytics" in x["title"].lower()) if j else 0
        print("GH",b,len(j) if j is not None else None,a,flush=True)
    except Exception as e: print("GH",b,"ERR")
for b in ["rippling","alloy","moderntreasury","deel","pagaya","mercury","sardine","unit","persona","vanta","hebbia","rogo","brex","bilt","figure","arc","jeeves","clear-street","public","kalshi","polymarket"]:
    try:
        r=requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{b}",timeout=15)
        j=r.json().get("jobs",[]) if r.ok else None
        a=sum(1 for x in j if "analyst" in x["title"].lower() or "analytics" in x["title"].lower()) if j else 0
        print("AS",b,len(j) if j is not None else None,a,flush=True)
    except Exception: print("AS",b,"ERR")
for b in ["kraken","wealthsimple","plaid","figure","ripple","lendingtree","valon","chainalysis","anchorage"]:
    try:
        r=requests.get(f"https://api.lever.co/v0/postings/{b}?mode=json",timeout=15)
        j=r.json() if r.ok else None
        a=sum(1 for x in j if "analyst" in x["text"].lower() or "analytics" in x["text"].lower()) if j else 0
        print("LV",b,len(j) if j is not None else None,a,flush=True)
    except Exception: print("LV",b,"ERR")
