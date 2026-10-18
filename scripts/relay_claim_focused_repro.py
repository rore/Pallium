"""Finite focused Linux mechanism experiment, NOT qualification or historical attribution."""
from contextlib import contextmanager,ExitStack
import importlib.metadata, importlib.util, json, os
from pathlib import Path
import subprocess,sys,time
if __name__=='__main__':
 import hashlib
 directory=Path(sys.argv[2]);directory.mkdir(parents=True,exist_ok=True)
 if sys.argv[1]=='--status':
  summary={'complete':False,'timing_complete':False,'resource_complete':False,'pressure_adequate':False,'issues':[]}
  try:
   reports=[]
   for mode in ('baseline','cpu'):
    for repeat in (1,2):
     file=directory/f'{mode}-{repeat}.json'
     if file.stat().st_size>1_000_000:raise ValueError('oversize')
     report=json.loads(file.read_text(encoding='utf-8'))
     if report['mode']!=mode or report['repeat']!=repeat:raise ValueError('identity')
     reports.append(report)
   runtime=json.loads((directory/'runtime.json').read_text(encoding='utf-8'))
   process=json.loads((directory/'process.json').read_text(encoding='utf-8'))
   result=json.loads((directory/'run-result.json').read_text(encoding='utf-8'))
   if runtime['platform']!='linux' or not runtime['python'].startswith('3.12.') or not runtime['source'] or not runtime['distributions']:raise ValueError('runtime')
   if result['exit_code']!=0 or len(process['selected_affinity'])!=1 or process['nice_after']<process['nice_before']:raise ValueError('process')
   summary['timing_complete']=all(r['third_is_exact_claim'] is True and r['provider_scope_matches'] is True and not r['unexpected_observer_issues'] and not r['unexpected_capture_issues'] and r['capture']['seen']==3 and r['capture']['dropped']==0 and not r['owned_helpers_remaining'] and not r.get('forced_helper_kill') for r in reports)
   summary['resource_complete']=all(r['capture']['complete'] is True for r in reports)
   summary['pressure_adequate']=all(r['claim_pressure_adequate'] is True for r in reports if r['mode']=='cpu')
   summary['original_all_pass']=all(r['original_assertions_passed'] is True for r in reports)
   summary['resource_issues']=sorted({x for r in reports for rec in r['capture']['records'] for x in rec['issues']})
   summary['complete']=all(summary[k] for k in ('timing_complete','resource_complete','pressure_adequate'))
   if not summary['complete']:summary['issues']=['incomplete_or_unsupported_evidence']
  except Exception:summary['issues']=['missing_malformed_or_failed_evidence']
  (directory/'evidence-status.json').write_text(json.dumps(summary,sort_keys=True),encoding='utf-8')
  raise SystemExit(0 if summary['complete'] else 1)
 assert sys.argv[1]=='--run' and sys.platform=='linux' and sys.version_info[:2]==(3,12)
 initial=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,{initial[0]})
 before=os.getpriority(os.PRIO_PROCESS,0);after=max(10,before);os.nice(after-before)
 assert sorted(os.sched_getaffinity(0))==[initial[0]] and os.getpriority(os.PRIO_PROCESS,0)==after
 os.environ['PALLIUM_FOCUSED_EVIDENCE']=str(directory.resolve())
 import tempfile
 private_temp=Path(tempfile.mkdtemp(prefix='pallium-focused-',dir=os.environ.get('RUNNER_TEMP')))
 assert Path.cwd().resolve() not in private_temp.resolve().parents
 consumed=('scripts/relay_claim_focused_repro.py','scripts/relay_claim_cpu_helper.py','scripts/relay_claim_acquisition_diagnostic.py','tests/test_agent_relay_hooks.py','tests/conftest.py','core/relay.py','storage/sqlite.py','storage/sqlite_queue.py','storage/sqlite_relay.py','app/config.py','pyproject.toml','.github/workflows/ci.yml')
 process={'pid':os.getpid(),'pytest_temp':str(private_temp/'p'),'initial_affinity':initial,'selected_affinity':sorted(os.sched_getaffinity(0)),'nice_before':before,'nice_after':after,'source':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in consumed},'scope':'owned bootstrap calling thread before pytest imports; provider/helper inheritance verified separately'}
 (directory/'process.json').write_text(json.dumps(process,sort_keys=True),encoding='utf-8')
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
 import pytest
 exit_code=2
 try:exit_code=pytest.main([__file__,'-q','-x','-n','0','-p','no:cacheprovider','--basetemp',str(private_temp/'p'),'--junitxml',str(directory/'junit.xml')])
 finally:(directory/'run-result.json').write_text(json.dumps({'exit_code':int(exit_code),'pid':os.getpid(),'scope':'finite4 experiment outcomes, not original assertions/release qualification','owned_helpers':'each trial explicitly waits all owned helpers; no exhaustive descendant history'}),encoding='utf-8')
 raise SystemExit(exit_code)

import pytest
from tests.conftest import test_db_url, isolated_claude_wake_state
from tests.conftest import client as native_client
from tests.test_agent_relay_hooks import isolated_hook_state
from tests.test_agent_relay_hooks import test_codex_exact_wake_real_http_response_delay_is_bounded_and_traceable as journey

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('_focused_original_recorder',ROOT/'scripts/relay_claim_acquisition_diagnostic.py')
observer=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(observer)
# Existing exact observer guard remains; no dependency pin/install change.
assert importlib.metadata.version('sqlalchemy')==observer.EXPECTED_SQLALCHEMY

@pytest.fixture
def observed_client(test_db_url,monkeypatch,request):
 capture=observer.Capture(0)
 try:
  with ExitStack() as observation:
   with contextmanager(native_client.__wrapped__)(test_db_url,monkeypatch) as client:
    storage=client.app.state.pallium_service._storage
    observer.install(capture,observation,storage)
    observer.install_http(capture,observation,client)
    assert not capture.issues
    yield client,capture,observation
 finally:
  # Always retain evidence AFTER ordinary teardown/restoration, including close errors.
  native_error=sys.exc_info()[0]
  receipt=getattr(request.node,'_focused_receipt',{'setup_failed':True})
  receipt['teardown_error_type']=None if native_error is None else native_error.__name__
  if native_error is not None:capture.failed=True
  try:
   payload=capture.payload()
   receipt['capture']=payload
   third=next((r for r in payload['records'] if r['ordinal']==3),None)
   if third is not None:
    span=next(s for s in third['spans'] if s['phase']=='turn')
    entered=third['anchor_monotonic_ns']+span['entered_wall_ns'];returned=third['anchor_monotonic_ns']+span['returned_wall_ns']
    receipt['claim_helper_overlap_ns']=[max(0,min(returned,c['end_ns'])-max(entered,c['start_ns'])) for c in receipt.get('children',[]) if 'end_ns' in c]
    receipt['claim_pressure_adequate']=(receipt.get('third_is_exact_claim',False) and receipt.get('provider_scope_matches',False) and not receipt.get('trigger_error_type') and any(receipt['claim_helper_overlap_ns'])) if receipt.get('mode')=='cpu' else None
   else:receipt['claim_pressure_adequate']=False
   receipt['unexpected_observer_issues']=[x for r in payload['records'] for x in r['issues'] if x!='resource_unsupported']
   resource_only=all(set(r['issues'])<={'resource_unsupported'} for r in payload['records'])
   receipt['unexpected_capture_issues']=[x for x in payload['issues'] if not (x=='incomplete_turn' and resource_only)]
   path=Path(os.environ['PALLIUM_FOCUSED_EVIDENCE'])
   (path/f"{request.node.callspec.id}.json").write_text(json.dumps(receipt,sort_keys=True))
   if native_error is None:
    assert not receipt['unexpected_observer_issues'],receipt['unexpected_observer_issues']
    assert not receipt['unexpected_capture_issues'],receipt['unexpected_capture_issues']
    assert not payload['dropped'] and payload['seen']<=3
  except BaseException:
   if native_error is None:raise
   print('focused evidence emission failed during original teardown failure',file=sys.stderr)

@pytest.mark.parametrize('mode,repeat',[('baseline',1),('baseline',2),('cpu',1),('cpu',2)])
def test_focused_original_http(observed_client,monkeypatch,tmp_path,capsys,request,mode,repeat):
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12)
 client,capture,observation=observed_client
 # Bootstrap changes affinity/nice BEFORE pytest imports; assert inherited values.
 affinity=sorted(os.sched_getaffinity(0));assert len(affinity)==1
 mask=1<<affinity[0]
 priority=os.getpriority(os.PRIO_PROCESS,0)
 process=json.loads((Path(os.environ['PALLIUM_FOCUSED_EVIDENCE'])/'process.json').read_text())
 assert affinity==process['selected_affinity'] and priority==process['nice_after']
 receipt={'mode':mode,'repeat':repeat,'scope':'induced Linux312 mechanism; not attribution to exact historical event','mask':mask,'priority':priority,'original_assertions_passed':False,'children':[],'original_failure':None}
 request.node._focused_receipt=receipt
 children=[]; pressure=tmp_path/'pressure';pressure.mkdir()
 try:
  if mode=='cpu':
   for i in range(8):
    child=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('relay_claim_cpu_helper.py')),str(pressure),str(i)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True)
    children.append(child)
    os.set_blocking(child.stdin.fileno(),False)
    assert os.get_blocking(child.stdin.fileno()) is False
   ready_deadline=time.monotonic()+8
   while not all((pressure/f'{i}.ready').exists() for i in range(8)):
    if time.monotonic()>ready_deadline or any(p.poll() is not None for p in children): raise AssertionError('owned helper readiness failed')
    time.sleep(.01) # Preparation only, before original journey/hook deadline.
   for i in range(8):
    ready=json.loads((pressure/f'{i}.ready').read_text()); assert ready['mask']==mask and ready['priority']==priority
  storage=client.app.state.pallium_service._storage
  native_turn=storage.relay_turn
  receipt['provider_entries']=0
  def trigger_third(*args,**kwargs):
   receipt['provider_entries']+=1
   if receipt['provider_entries']==3:
    entered,cpu=time.monotonic_ns(),time.thread_time_ns()
    receipt['provider_affinity']=sorted(os.sched_getaffinity(0))
    receipt['provider_nice']=os.getpriority(os.PRIO_PROCESS,0)
    receipt['provider_scope_matches']=(receipt['provider_affinity']==affinity and receipt['provider_nice']==priority)
    exact=(kwargs.get('runtime')=='codex' and kwargs.get('session_ref')=='target-session' and kwargs.get('container_ref')=='git:example/repo' and isinstance(kwargs.get('exact_delivery_id'),str) and kwargs['exact_delivery_id'].startswith('relay-delivery-'))
    receipt['third_is_exact_claim']=exact
    try:
     if mode=='cpu' and exact:
      receipt['pressure_start_ns']=entered
      receipt['pressure_deadline_ns']=entered+3_000_000_000
      signal=(str(receipt['pressure_deadline_ns'])+'\n').encode('ascii')
      receipt['trigger_signals_sent']=0
      for child in children:
       if os.write(child.stdin.fileno(),signal)!=len(signal):raise RuntimeError('short pressure signal')
       receipt['trigger_signals_sent']+=1
    except BaseException as error:
     receipt['trigger_error_type']=type(error).__name__
    finally:
     receipt['trigger']={'entered_ns':entered,'returned_ns':time.monotonic_ns(),'cpu_ns':time.thread_time_ns()-cpu}
   return native_turn(*args,**kwargs)
  capture.patch(observation,storage,'relay_turn',trigger_third)
  receipt['journey_entered_ns']=time.monotonic_ns()
  try:
   journey(client,monkeypatch,tmp_path,capsys,2.2,False,'claimed',False,False)
   receipt['original_assertions_passed']=True
  except AssertionError as exc:
   # Keep every original assertion. Experiment records failure, never calls it product green.
   tb=exc.__traceback__
   while tb.tb_next:tb=tb.tb_next
   receipt['original_failure']={'file':Path(tb.tb_frame.f_code.co_filename).name,'line':tb.tb_lineno,'type':'AssertionError'}
   capture.failed=True
  except BaseException as exc:
   receipt['unexpected_journey_error_type']=type(exc).__name__
   capture.failed=True
   raise
  finally:
   receipt['journey_returned_ns']=time.monotonic_ns()
   stages=tmp_path/'delayed-http-stages.json'
   if stages.exists():receipt['original_stages']=json.loads(stages.read_text(encoding='utf-8'))
 finally:
  for child in children:
   if child.stdin is not None and not child.stdin.closed:
    try:child.stdin.close()
    except OSError:pass
  cleanup_deadline=time.monotonic()+5
  for child in children:
   try:child.wait(timeout=max(0,cleanup_deadline-time.monotonic()))
   except subprocess.TimeoutExpired:pass
  for child in children:
   if child.poll() is None:child.kill();receipt['forced_helper_kill']=True
  killed_deadline=time.monotonic()+5
  for child in children:
   if child.poll() is None:child.wait(timeout=max(0,killed_deadline-time.monotonic()))
  receipt['owned_helpers_remaining']=sum(p.poll() is None for p in children)
  for i,child in enumerate(children):
   info={'pid':child.pid,'exit':child.returncode}
   if (pressure/f'{i}.done').exists():info.update(json.loads((pressure/f'{i}.done').read_text()))
   receipt['children'].append(info)
 assert receipt['owned_helpers_remaining']==0 and not receipt.get('forced_helper_kill')
 if mode=='cpu':
  assert all(c['exit']==0 and c.get('cpu_ns',0)>0 and c.get('batches',0)>0 and c.get('mask')==mask for c in receipt['children'])
 # All helpers share the same absolute3s deadline; cleanup waits do not extend compute.
 # Platform/resource support, effective overlap and reproducibility are assessed from receipts.
