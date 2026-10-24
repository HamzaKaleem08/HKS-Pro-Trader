import requests,re,json
URLS=["https://www.mexc.com/market-data-download?search=TNK&type=kline",
"https://www.mexc.co/en-US/market-data-download?search=TNK&type=kline",
"https://www.mexc.com/market-data-download?search=TNK&type=trade"]
for url in URLS:
 try:
  resp=requests.get(url,timeout=18,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"})
  raw=resp.text
  print("PROBE",json.dumps({"url":url,"status":resp.status_code,"length":len(raw),"final":resp.url,"tnk_count":len(re.findall("TNK",raw,re.I)),"search_type_present":"search=TNK" in raw,"redirect":resp.history[0].status_code if resp.history else None,"start":raw[:160]}))
  for term in ["market-data-download","download","kline","archive","TNKUSDT","__NEXT_DATA__","api.mexc"]:
   refs=[m.start() for m in re.finditer(re.escape(term),raw,re.I)]
   if refs:print("TERM",term,len(refs),"first",raw[max(0,refs[0]-160):refs[0]+250].replace("\n"," ")[:450])
  scr=re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',raw,re.I)
  print("SCRIPTS",json.dumps(scr[-30:])[:5000])
 except Exception as e:print("ERROR",url,str(e)[:300])
