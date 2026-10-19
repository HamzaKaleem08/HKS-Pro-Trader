"""Actual isolated Pyodide strategy execution on disposable local Chromium.

No server-side/host execution of pasted strategies, publication or downloads.
Synthetic observation tests are separate from genuine cached-candle runs.
"""
import argparse,copy,csv,gzip,hashlib,json,os,re,shutil,socket,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from decimal import Decimal as D,localcontext,ROUND_HALF_EVEN
from pathlib import Path
from types import SimpleNamespace as NS
from playwright.sync_api import sync_playwright
from smc_reference import snapshot
from verify_consent_browser import reconcile,save_gzip

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()
M=60000;Q=15*M;H=60*M

def ms(s):return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)

def candle(t,period,o='100',h='101',l='99',c='100'):
    return dict(open_ms=t,interval_ms=period,open=str(o),high=str(h),low=str(l),close=str(c),volume='10')

def pattern(original='LONG',hour=8,minute=0,fvg=True,dual=False,bias=None):
    start=ms('2025-11-02T00:00:00Z')+hour*H+minute*M;end=start+Q
    bars=[candle(start-(49-i)*Q,Q) for i in range(50)]
    if original=='LONG':
        bars[-1]=candle(start,Q,'100','100.8','98','100.5')
        bars[-2]=candle(start-Q,Q,'100','103','99','102')
        if fvg:bars[-3]=candle(start-2*Q,Q,'96','97','95','96')
    else:
        bars[-1]=candle(start,Q,'100','102','99.2','99.5')
        bars[-2]=candle(start-Q,Q,'100','101','97','98')
        if fvg:bars[-3]=candle(start-2*Q,Q,'104','105','103','104')
    if dual:
        bars[-1]=candle(start,Q,'100','102','98','100')
        bars[-2]=candle(start-Q,Q,'100','101','97','98')
        bars[-3]=candle(start-2*Q,Q)
    bias=bias or original
    hour_end=end//H*H
    hourly=[candle(hour_end-(21-i)*H,H) for i in range(21)]
    if bias=='LONG':hourly[-1]=candle(hour_end-H,H,'100','103','99','102')
    elif bias=='SHORT':hourly[-1]=candle(hour_end-H,H,'100','101','97','98')
    return end,bars,hourly

def observation(sym,end,bars,hourly,position=None,last_exit=None):
    price=bars[-1]['close'];c=candle(end-M,M,price,price,price,price)
    return dict(symbol=sym,bars=[dict(c,open_ms=end-2*M),c],position=position,
        account=dict(equity='1000',cash='1000',reserved_capital='0',reserved_risk='0'),
        contexts={'15m':bars,'1h':hourly},last_exit=last_exit)

def oracle(bars,hourly):
    def convert(b):return NS(**{k:D(v) if k in ['open','high','low','close','volume'] else v for k,v in b.items()})
    return snapshot(tuple(map(convert,bars)),tuple(map(convert,hourly)))

def synthetic_cases():
    cases=[]
    def entry(label,**options):
        end,bars,hourly=pattern(**options);s=oracle(bars,hourly)
        expected={'enter':{'side':s['executed_side'],'stop':{'mode':'fraction','value':s['stop_fraction']},'target':None}} if s['qualifies'] else None
        cases.append(dict(label=label,frame=observation('CASE'+str(len(cases)),end,bars,hourly),expected=expected,source_oracle=s))
    entry('original_LONG_executes_SHORT')
    entry('original_SHORT_executes_LONG',original='SHORT')
    entry('dual_sweep_LONG_precedence_opposite_bear_MSS',dual=True)
    entry('score_exactly_75_accepted',fvg=False,bias='SHORT')
    entry('score_65_rejected_outside_session',hour=7,fvg=False,bias='SHORT')
    entry('outside_session_not_hard_ban',hour=7,bias='SHORT')
    entry('session_08_inclusive',hour=8,fvg=False,bias='SHORT')
    entry('session_21_45_inclusive',hour=21,minute=45,fvg=False,bias='SHORT')
    entry('session_22_exclusive',hour=22,fvg=False,bias='SHORT')
    end,bars,hourly=pattern(original='SHORT')
    hourly=[dict(b,open='100',close='100',high='101',low='99') for b in hourly]
    s=oracle(bars,hourly);assert s['htf']=='SHORT'
    cases.append(dict(label='equal_hourly_SMA_bias_SHORT',frame=observation('EQUAL',end,bars,hourly),
                      expected={'enter':{'side':'LONG','stop':{'mode':'fraction','value':s['stop_fraction']},'target':None}}))
    for factor,clamp in [('0.01','0.008'),('10','0.03'),('0.3',None)]:
        end,bars,hourly=pattern()
        for bar in bars:
            for field in ('open','high','low','close'):bar[field]=str(D(100)+(D(bar[field])-100)*D(factor))
        s=oracle(bars,hourly);assert s['qualifies']
        if clamp is not None:assert D(s['stop_fraction'])==D(clamp)
        rounded=D(s['stop_fraction']).quantize(D('1e-18'),rounding=ROUND_HALF_EVEN)
        assert abs(rounded-D(s['stop_fraction']))<=D('0.5e-18')
        cases.append(dict(label='ATR_'+(clamp or 'nonclamped_API_precision'),frame=observation('ATR'+str(len(cases)),end,bars,hourly),
            expected={'enter':{'side':'SHORT','stop':{'mode':'fraction','value':str(rounded)},'target':None}}))
    for side in ('LONG','SHORT'):
        for progress in ('-10','0','49.99','50','79.99','80','84.99','85','100','105','150'):
            end,bars,hourly=pattern();sign=1 if side=='LONG' else -1
            price=D(100)+sign*D(4)*D(progress)/100
            bars[-1].update(open=str(price),high=str(price+1),low=str(price-1),close=str(price))
            p=dict(trade_id='TRAIL'+str(len(cases)),side=side,entry_ms=end-H,entry_price='100',quantity='1',
                original_quantity='1',stop='98' if side=='LONG' else '102',initial_stop='98' if side=='LONG' else '102',
                target=None,planned_risk='2',mfe='0',mae='0',unrealized_fraction=str((price-100)/100*sign))
            expected=None
            if D(progress)>=50:
                lock=(D(progress)//5)*5-10 if D(progress)>=80 else D(10)
                expected={'stop':str(D(100)+sign*D(4)*lock/100)}
            cases.append(dict(label='original_trail_'+side+'_'+progress,frame=observation('TRAIL'+str(len(cases)),end,bars,hourly,p),expected=expected))
        f=copy.deepcopy(cases[-1]['frame']);f['symbol']='RATCHET'+side;f['position']['stop']='110' if side=='LONG' else '90'
        cases.append(dict(label='never_loosen_'+side,frame=f,expected=None))
    end,bars,hourly=pattern()
    for label,timestamp,expected in [('same_15m_exit_blocks_reentry',end-M,None),('previous_15m_exit_allows_entry',end-Q-M,
        {'enter':{'side':'SHORT','stop':{'mode':'fraction','value':oracle(bars,hourly)['stop_fraction']},'target':None}})]:
        last=dict(exit_ms=timestamp+M,fill_window_start_ms=timestamp,fill_window_end_ms=timestamp+M,exit_reason='INITIAL_STOP')
        cases.append(dict(label=label,frame=observation('EXIT'+str(len(cases)),end,bars,hourly,last_exit=last),expected=expected))
    cases.append(dict(label='no_entry_between_15m_closes',frame=observation('MIDMINUTE',end+M,bars,hourly),expected=None))
    for label,change in [('future_hour_refused','future'),('duplicate_context_refused','duplicate'),('invalid_OHLC_refused','ohlc'),('missing_context_refused','missing')]:
        frame=observation('BAD'+str(len(cases)),end,copy.deepcopy(bars),copy.deepcopy(hourly))
        if change=='future':frame['contexts']['1h'][-1]['open_ms']+=H
        elif change=='duplicate':frame['contexts']['15m'][-2]['open_ms']=frame['contexts']['15m'][-3]['open_ms']
        elif change=='ohlc':frame['contexts']['1h'][-1]['high']='NaN'
        elif change=='missing':frame['contexts']={}
        cases.append(dict(label=label,frame=frame,error=True))
    return cases

def check_decision(actual,expected):
    if expected is None:assert actual is None,actual;return
    assert set(actual)==set(expected),(actual,expected)
    if 'enter' in expected:
        assert actual['enter']['side']==expected['enter']['side']
        assert actual['enter']['target'] is None
        assert actual['enter']['stop']['mode']=='fraction'
        assert D(actual['enter']['stop']['value'])==D(expected['enter']['stop']['value'])
    else:assert D(actual['stop'])==D(expected['stop'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--resume-evidence',type=Path)
    ap.add_argument('--start',default='2025-11-02T00:00');ap.add_argument('--end',default='2025-11-05T00:00');args=ap.parse_args()
    out=ROOT/'evidence/smc-compat-v1/browser';out.mkdir(exist_ok=False)
    record={'synthetic_tests':[],'genuine_runs':{},'baseline_parity':[], 'page_errors':[],
            'deployment':False,'physical_android_tested':False,'network_market_requests':False,
            'strategy_file_sha256':hashlib.sha256(SOURCE.encode()).hexdigest()}
    if args.resume_evidence:
        previous=json.loads((args.resume_evidence/'BROWSER_EVIDENCE.json').read_text())
        record['synthetic_tests']=previous['synthetic_tests']
        record['genuine_runs']=previous['genuine_runs']
        record['baseline_parity']=previous.get('baseline_parity',[])
        if 'restart' in previous:record['restart']=previous['restart']
        record['continued_from']=str(args.resume_evidence)
        for item in args.resume_evidence.iterdir():
            if item.suffix in ('.gz','.csv','.png'):shutil.copyfile(item,out/item.name)
        definition=dict(schema_version=1,kind='PYTHON_STRATEGY',name='HKS Legacy SMC Reverse — compatibility V1',code=SOURCE)
        expected_strategy=hashlib.sha256(json.dumps(definition,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        for item in out.glob('*result.json.gz'):
            assert json.loads(gzip.decompress(item.read_bytes()))['result']['strategy_hash']==expected_strategy,'Cannot reuse a different strategy version'
    log=(out/'SERVER.log').open('w');server=None
    try:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        server=subprocess.Popen([sys.executable,str(ROOT/'serve.py'),'--port',str(port)],stdout=log,stderr=log)
        origin=f'http://127.0.0.1:{port}';record['origin']=origin
        with tempfile.TemporaryDirectory(prefix='hks-smc-browser-',dir='/tmp') as tmp,sync_playwright() as p:
            env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
            env.update(XDG_CONFIG_HOME=tmp,XDG_CACHE_HOME=tmp)
            ctx=p.chromium.launch_persistent_context(str(Path(tmp)/'profile'),executable_path='/usr/bin/chromium',
                headless=True,chromium_sandbox=True,env=env,viewport={'width':1440,'height':1000},accept_downloads=True)
            page=ctx.pages[0];page.set_default_timeout(30000)
            page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
            page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio')
            assert page.evaluate('crossOriginIsolated')
            record['sourceHash']=page.evaluate('HKSStudio.sourceHash')
            if args.resume_evidence:assert previous['sourceHash']==record['sourceHash']
            info=page.evaluate('''async code=>{window.probe=new HKSStudio.SandboxClient();return await probe.init(code);}''',SOURCE)
            assert info['origin']=='null';record['strategy_isolation']=info
            for case in ([] if record['synthetic_tests'] else synthetic_cases()):
                answer=page.evaluate('async f=>JSON.parse(await probe.step(f))',case['frame'])
                if case.get('error'):assert answer.get('error'),answer
                else:assert not answer.get('error'),answer;check_decision(answer['decision'],case['expected'])
                record['synthetic_tests'].append(dict(label=case['label'],passed=True,answer=answer,
                    source_oracle=case.get('source_oracle')))
            page.evaluate('probe.stop()');print('Synthetic actual Pyodide callbacks passed:',len(record['synthetic_tests']),flush=True)
            # Actual published-UI controls, not mocked worker calls.
            page.fill('#definition',SOURCE);page.fill('#strategyName','HKS Legacy SMC Reverse — compatibility V1')
            page.click('details.advanced > summary')
            page.fill('#risk','0.01');page.fill('#maxPositions','3');page.fill('#fees','10');page.fill('#slippage','2')
            page.fill('#start',args.start);page.fill('#end',args.end)
            page.check('#trusted');page.check('#diagnostic')
            page.click('#validate');page.wait_for_function("()=>document.querySelector('#message').textContent.includes('1320 required pre-window')")
            for mode in ('shared','individual'):
                if mode in record['genuine_runs']:continue
                page.select_option('#mode',mode)
                page.check('#trusted')
                if mode=='individual':
                    page.evaluate('''()=>{window.restartSample=null;window.addEventListener('hks-checkpoint',async e=>{
                        if(e.detail.next_ms>=Date.parse('2025-11-03T00:00:00Z')&&!window.restartSample){
                            window.restartSample={waiting:true};const job=structuredClone(HKSStudio.job);
                            window.restartSample={job,snapshot:await HKSStudio.store.checkpoint(job)};
                        }});}''')
                before=page.evaluate('HKSStudio.job?.id')
                page.click('#runButton')
                page.wait_for_function('x=>!HKSStudio.running&&HKSStudio.job?.id!==x.before&&["COMPLETE","FAILED"].includes(HKSStudio.job?.status)&&HKSStudio.job?.request.config.mode===x.mode',arg={'before':before,'mode':mode},timeout=240000)
                assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
                answer=page.evaluate('HKSStudio.result');result=answer['result']
                assert not result['synthetic'] and result['market']=='USDT_LINEAR_PERPETUAL'
                assert result['config']['risk_fraction']=='0.01' and result['config']['max_positions']==3
                assert result['trades'] or result['open_positions']
                assert all(t['target'] is None for t in result['trades']+result['open_positions'])
                assert all(t['side']=='LONG' for t in result['trades']+result['open_positions'])
                checks=reconcile(result)
                record['genuine_runs'][mode]={'result_hash':result['result_hash'],'accounts':result['accounts'],
                    'closed':len(result['trades']),'open':len(result['open_positions']),'metrics':answer['metrics'],
                    'reconciliation':checks,'artifact':save_gzip(out/(mode+'-genuine-result.json.gz'),answer)}
                with page.expect_download() as d:page.click('#exportTrades')
                filename=out/(mode+'-trades.csv');d.value.save_as(filename)
                csv_rows=list(csv.DictReader(filename.open()));assert len(csv_rows)==len(result['trades'])
                record['genuine_runs'][mode]['csv_rows']=len(csv_rows)
                if mode=='individual':
                    sample=page.evaluate('window.restartSample');assert sample and 'snapshot' in sample
                    save_gzip(out/'restart-checkpoint.json.gz',sample)
                page.screenshot(path=str(out/(mode+'-desktop.png')),full_page=True)
                expected=result['result_hash'];page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio&&!!HKSStudio.result')
                assert page.evaluate('HKSStudio.result.result.result_hash')==expected
                assert page.is_checked('#diagnostic') and page.input_value('#definition')==SOURCE
                assert not page.is_checked('#trusted')
                record['genuine_runs'][mode]['reload_persistence']=True
                record['genuine_runs'][mode]['fresh_trust_acknowledgement_required_after_reload']=True
                print(mode,'genuine run:',len(result['trades']),'closed,',len(result['open_positions']),'open, hash',expected,flush=True)
            # Independent fresh worker restart from an actual SMC checkpoint.
            if 'restart' not in record:
                sample=json.loads(gzip.decompress((out/'restart-checkpoint.json.gz').read_bytes()))
                sample['job']['id']='smc-independent-restart';sample['job']['status']='CANCELLED'
                page.evaluate('''async saved=>{await HKSStudio.store.saveCheckpoint(saved.job,saved.snapshot);
                    await HKSStudio.showJob(saved.job.id);}''',sample)
                page.check('#trusted')
                page.click('#retry')
                page.wait_for_function('()=>!HKSStudio.running&&["COMPLETE","FAILED"].includes(HKSStudio.job?.status)',timeout=240000)
                assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
                answer=page.evaluate('HKSStudio.result')
                expected=json.loads(gzip.decompress((out/'individual-genuine-result.json.gz').read_bytes()))
                assert answer['result']==expected['result']
                record['restart']={'full_result_exactly_equal':True,'result_hash':answer['result']['result_hash'],'metrics':answer['metrics']}
                save_gzip(out/'restarted-genuine-result.json.gz',answer)
                print('Actual checkpoint fresh-worker restart exact full-result parity',flush=True)
            # Genuine original LONG -> SHORT at an independently identified
            # November event. A functional coverage fixture, not optimization.
            for mode in ('shared','individual'):
                if mode+'_reverse_SHORT' in record['genuine_runs']:continue
                page.fill('#start','2025-11-17T14:00');page.fill('#end','2025-11-17T16:00');page.select_option('#mode',mode)
                page.check('#trusted')
                before=page.evaluate('HKSStudio.job?.id')
                page.click('#runButton');page.wait_for_function('id=>!HKSStudio.running&&HKSStudio.job?.id!==id&&["COMPLETE","FAILED"].includes(HKSStudio.job?.status)',arg=before,timeout=90000)
                assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
                answer=page.evaluate('HKSStudio.result');r=answer['result']
                positions=r['trades']+r['open_positions'];assert positions and all(t['side']=='SHORT' for t in positions)
                reconcile(r)
                record['genuine_runs'][mode+'_reverse_SHORT']={'result_hash':r['result_hash'],'closed':len(r['trades']),
                    'open':len(r['open_positions']),'accounts':r['accounts'],'metrics':answer['metrics']}
                save_gzip(out/(mode+'-reverse-short-result.json.gz'),answer)
                print(mode,'genuine reverse SHORT verified',flush=True)
            # Every preserved financial parity fixture actually executes in the
            # browser; prior result hashes are expectations, not fresh claims.
            expected=json.loads((ROOT/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text())
            for entry in json.loads((ROOT/'web/catalog.json').read_text()):
                answer=page.evaluate('''async id=>{try{const b=await HKSStudio.fixture(id);return await new HKSStudio.BrowserEngine().run(b);}
                    catch(e){return {ok:false,error:e.message};}}''',entry['id'])
                baseline=expected[entry['id']]
                assert answer['ok']==baseline['ok'],(entry['id'],answer)
                if answer['ok']:assert answer['result']==baseline['result'],entry['id']
                record['baseline_parity'].append({'id':entry['id'],'passed':True,'ok':answer['ok'],
                    'result_hash':answer.get('result',{}).get('result_hash')})
                print('Frozen browser parity:',entry['id'],flush=True)
            page.set_viewport_size({'width':412,'height':915})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'mobile-emulation.png'),full_page=True)
            record['responsive_emulation_no_page_overflow']=True
            assert record['page_errors']==[],record['page_errors']
            ctx.close();record['passed']=True
    except BaseException as e:
        record['passed']=False;record['failure']=repr(e);raise
    finally:
        (out/'BROWSER_EVIDENCE.json').write_text(json.dumps(record,indent=2,default=str))
        if server:server.terminate();server.wait(timeout=10)
        log.close()

if __name__=='__main__':main()
