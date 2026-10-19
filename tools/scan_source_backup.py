"""Bounded source/embedded-archive secret scan; never prints matched values."""
import argparse,gzip,hashlib,io,json,os,re,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
 'private_key':rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----',
 'github_token':rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b',
 'aws_access_key':rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
 'google_api_key':rb'\bAIza[A-Za-z0-9_-]{35}\b',
 'slack_token':rb'\bxox[baprs]-[A-Za-z0-9-]{20,}\b',
 'jwt':rb'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{15,}\b',
 'credential_url':rb'https?://[^\s/@:\'"]{1,60}:[^\s/@\'"]{1,120}@[^\s/\'"]+',
 'literal_secret_assignment':rb'''(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|password|passwd|github[_-]?token|cloudflare[_-]?api[_-]?token)["']?\s*[:=]\s*["'][^"'\r\n]{12,}["']''',
}
IGNORE={'.git','__pycache__','qa-output'}
MAX_EXPANDED=128*1024**2

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path);args=ap.parse_args()
 findings=[];reviewed=[];files=0;archives=0;expanded_files=0;expanded_bytes=0;total=0
 names=['CLOUDFLARE_API_TOKEN','GITHUB_TOKEN','GH_TOKEN']
 secrets={n:os.environ[n].encode() for n in names if len(os.environ.get(n,''))>=8}
 def inspect(raw,name):
  for category,pattern in PATTERNS.items():
   for m in re.finditer(pattern,raw):
    line=raw[:m.start()].count(b'\n')+1
    # A single reviewed public Python documentation example, pinned to its
    # exact upstream source bytes. No blanket vendor/secret-pattern exemption.
    if (name=='web/vendor/pyodide/python_stdlib.zip!urllib/request.py'
        and category=='literal_secret_assignment' and line==56
        and hashlib.sha256(raw).hexdigest()=='94897f6f53f96839637ec3637318a51176b0076907099de0ade84f9338514318'
        and hashlib.sha256(raw.splitlines()[55]).hexdigest()=='03d7bb92b36fd2532fc5c217aeb6beceb9dd3d71f2318b7367ffd2ef0e564e4e'):
     reviewed.append({'path':name,'category':'public_upstream_documentation_example','line':56,
         'scope':'Exact checksum-pinned standard-library example; not an owner credential'});continue
    findings.append({'path':name,'category':category,'line':line})
  for n,value in secrets.items():
   if value in raw:findings.append({'path':name,'category':'configured_secret_literal','binding':n})
 for p in sorted(ROOT.rglob('*')):
  rel=p.relative_to(ROOT)
  if any(part in IGNORE for part in rel.parts):continue
  if p.is_symlink():findings.append({'path':str(rel),'category':'unexpected_symlink'});continue
  if not p.is_file():continue
  name=str(rel);raw=p.read_bytes();files+=1;total+=len(raw)
  if p.suffix.lower() in {'.db','.sqlite','.sqlite3','.pem','.key'} or '.wrangler' in rel.parts:
   findings.append({'path':name,'category':'prohibited_state_or_credential_path'})
  if name.startswith('web/candles/') or name.startswith('web/fixtures/genuine_'):
   findings.append({'path':name,'category':'historical_cache_payload'})
  if p.name.startswith('.env') or p.name.endswith('.env.example'):
   if not p.name.endswith('.example'):findings.append({'path':name,'category':'non_template_environment_file'})
   else:
    for line in raw.decode().splitlines():
     if line.strip() and not line.lstrip().startswith('#') and '=' in line and line.split('=',1)[1].strip():
      findings.append({'path':name,'category':'nonempty_environment_template'})
  inspect(raw,name)
  if p.suffix=='.zip':
   archives+=1
   with zipfile.ZipFile(io.BytesIO(raw)) as z:
    assert len(z.infolist())<=10000,'Archive file bound exceeded'
    for x in z.infolist():
     if x.is_dir():continue
     expanded_bytes+=x.file_size;expanded_files+=1
     assert expanded_bytes<=MAX_EXPANDED and x.file_size<=16*1024**2,'Archive expansion bound exceeded'
     inspect(z.read(x),name+'!'+x.filename)
  elif p.suffix=='.gz':
   archives+=1
   with gzip.GzipFile(fileobj=io.BytesIO(raw)) as z:plain=z.read(16*1024**2+1)
   assert len(plain)<=16*1024**2,'Gzip expansion bound exceeded'
   expanded_bytes+=len(plain);expanded_files+=1;assert expanded_bytes<=MAX_EXPANDED
   inspect(plain,name+'!expanded')
 record={'passed':not findings,'source_files_scanned':files,'source_bytes_scanned':total,
  'archives_scanned':archives,'expanded_files_scanned':expanded_files,'expanded_bytes_scanned':expanded_bytes,
  'configured_secret_bindings_checked':list(secrets),'findings':findings,'reviewed_public_examples':reviewed,
  'matched_values_printed':False,'scope':'All proposed source files and bounded archive contents; excludes .git, ignored QA output and bytecode.'}
 if args.output:
  args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(record,indent=2))
 print(json.dumps(record,indent=2))
 if findings:raise SystemExit(1)

if __name__=='__main__':main()
