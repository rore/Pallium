"""Released OpenCode V2 + production plugin + real Pallium HTTP, local provider only."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

pytestmark = pytest.mark.slow


def _assert_session_list(page, expected):
    """An unfiltered limit=2 short page proves zero or one session at this read."""
    assert isinstance(page, dict) and isinstance(page.get("data"), list)
    rows = page["data"]
    assert len(rows) < 2, "full session page cannot prove a sole fresh session"
    assert all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in rows)
    assert [row["id"] for row in rows] == expected


def _primary_gate(headers, target, first, entered, lock):
    """Route the actual provider request, never its payload or delivery success."""
    with lock:
        try:
            raw = headers.get("x-pallium-fixture", "")
            assert 0 < len(raw) <= 4096
            tag = json.loads(raw)
            assert isinstance(tag, dict) and tag.get("version") == 1
            assert isinstance(target, str) and tag.get("session") == target
            assert isinstance(tag.get("instance"), str) and 0 < len(tag["instance"]) <= 64
            if first["value"] is None:
                assert tag["instance"] == first["instance"]
            kind = tag.get("kind")
            assert kind in ("primary", "title", "compaction", "generate")
            if kind != "primary":
                assert "prefix" not in tag
                return False  # Auxiliary output must not wait for the primary it precedes.
            if first["value"] is None:
                first["value"] = {"tag": tag, "error": "invalid first primary identity"}
                expected = tag.get("expected")
                assert tag.get("prefix") is True and tag.get("completed") is True and tag.get("error") is None
                assert type(tag.get("invocation")) is int and tag["invocation"] > 0
                assert isinstance(expected, dict) and expected.get("session") == target
                assert isinstance(tag.get("input"), str) and re.fullmatch(r"msg_[A-Za-z0-9_-]{1,508}", tag["input"])
                assert expected.get("input") == tag["input"]
                assert type(expected.get("generation")) is int and expected["generation"] >= 1
                assert isinstance(expected.get("delivery"), str) and re.fullmatch(r"relay-delivery-[0-9a-f]{32}", expected["delivery"])
                first["value"]["error"] = None
            entered.set()  # FIRST is latched before gating; later requests cannot replace it.
            return True
        except (AssertionError, ValueError, TypeError, KeyError):
            if first["value"] is None:
                first["value"] = {"tag": None, "error": "invalid first request identity"}
            entered.set()  # Wake Python main, not a handler-thread-only assertion/timeout.
            return False


def _assert_first_primary(first, target, delivery, prompts):
    result = first["value"]
    assert result is not None and result["error"] is None, result
    tag = result["tag"]
    assert tag["session"] == target and tag["prefix"] is True and tag["completed"] is True
    assert len(prompts) == 1, "first prefix must have one independently observed wake.prompt"
    prompt = prompts[0]
    assert prompt["sessionID"] == target and prompt["inputID"] == tag["input"]
    assert tag["expected"] == {"session": target, "input": prompt["inputID"], "delivery": delivery,
                               "generation": prompt["metadata"]["generation"]}
    assert prompt["metadata"]["delivery_id"] == delivery


@pytest.mark.parametrize("existing,phase,retired", [
    (False, "lookup", "other"), (True, "lookup", "other"),
    (False, "caller", "other"), (True, "caller", "other"),
    (False, "lookup", "same"), (False, "lookup", "recreated"),
    (False, "lookup", "dispose"), (False, "lookup", "created"),
])
def test_assistant_ownership_retirement_through_http_and_history(client, tmp_path, existing, phase, retired):
    """Public plugin callbacks use a controlled native client and real Pallium HTTP."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "remote", "add", "origin",
                    "https://example.test/team/ownership.git"], check=True)
    attempted, stored, closed = [], [], []

    class OwnershipHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.loads(raw) if raw else None
            if self.path == "/items":
                attempted.extend(body)
            if self.path == "/relay/sessions/close":
                closed.append(body["session_ref"])
            response = client.request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if self.path == "/items" and response.is_success:
                stored.extend(zip(body, response.json()))
            payload = response.content
            try:
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), OwnershipHTTP)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    program = tmp_path / "ownership-caller.mjs"
    program.write_text(r"""import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
const {default:production}=await import(process.env.OWNERSHIP_PLUGIN);
const config=JSON.parse(process.env.OWNERSHIP_CASE),cwd=process.env.OWNERSHIP_DIRECTORY;
const sessionID='ses_ownership_a',other='ses_ownership_b',hooks={},disposed=[];
const defer=()=>{let resolve;const promise=new Promise(done=>resolve=done);return{promise,resolve}};
const entered=defer(),release=defer();
let waiting,acknowledge,lookup=false,gap=false,eventDone,contextReads=0,locationReads=0;
let text='OWNERSHIP_שלום',cleanup;
const deliver=(id,type='session.deleted')=>{
 assert.equal(typeof waiting,'function','subscriber must await the public event');
 const done=defer();acknowledge=done.resolve;
 const resolve=waiting;waiting=null;resolve({value:{type,data:{sessionID:id}},done:false});
 return done.promise;
};
const ctx={location:{directory:cwd},app:{log(){}},session:{
 hook:async(name,callback)=>{hooks[name]=callback;return{dispose:()=>disposed.push(name)}},
 get:async({sessionID:id})=>{
  if(id===sessionID&&lookup){lookup=false;entered.resolve();await release.promise}
  return{location:{get directory(){
   if(id===sessionID&&gap){gap=false;locationReads++;eventDone=deliver(other)}
   return cwd;
  }}};
 },
 context:async()=>{contextReads++;return{data:[
  {type:'assistant',id:'msg_ownership_'+(text.startsWith('SUCCESSOR')?'new':'old'),
   time:{created:0,completed:1},content:[{type:'text',text}]},
 ]}},
},event:{subscribe:({signal})=>({
 [Symbol.asyncIterator](){return this},
 next(){
  acknowledge?.();acknowledge=null;
  if(signal.aborted)return Promise.resolve({done:true});
  return new Promise(resolve=>{waiting=resolve;
   signal.addEventListener('abort',()=>resolve({done:true}),{once:true});
  });
 },
})}};
try{
 cleanup=await production.setup(ctx);
 if(config.existing)await hooks.prompt({sessionID,messageID:'msg_ownership_seed',prompt:{text:'generic seed'}});
 lookup=config.phase==='lookup';gap=config.phase==='caller';
 const capture=hooks.compaction({sessionID});
 if(config.phase==='lookup'){
  await entered.promise;
  if(config.retired==='dispose')await cleanup();
  else if(config.retired==='created')await deliver(sessionID,'session.created');
  else{
   await deliver(config.retired==='other'?other:sessionID);
   if(config.retired==='recreated')await deliver(sessionID,'session.created');
  }
  release.resolve();
 }
 await capture;
 if(eventDone)await eventDone;
 const initialReads=contextReads;
 if(['same','recreated'].includes(config.retired)){
  text='SUCCESSOR_שלום';await hooks.compaction({sessionID});
 }
 writeFileSync(process.env.OWNERSHIP_REPORT,JSON.stringify({initialReads,contextReads,locationReads}));
}finally{
 release.resolve();await cleanup?.();
 assert.deepEqual([...disposed].sort(),['compaction','context','prompt']);
}
""", encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PALLIUM_", "OPENCODE_", "OPENAI_", "ANTHROPIC_"))
           and not key.endswith("API_KEY")}
    private = tmp_path / "profile"
    private.mkdir()
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        env[key] = str(private)
    env.update(PALLIUM_PORT=str(server.server_port), PALLIUM_HOOK_ACTOR_REF="ownership-actor",
               OWNERSHIP_PLUGIN=(root / "integrations/opencode/.opencode/plugins/pallium-v2.mjs").as_uri(),
               OWNERSHIP_DIRECTORY=str(workspace), OWNERSHIP_REPORT=str(tmp_path / "ownership-report.json"),
               OWNERSHIP_CASE=json.dumps({"existing": existing, "phase": phase, "retired": retired}))
    try:
        result = subprocess.run([shutil.which("node") or "node", str(program)], env=env, cwd=workspace,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        (tmp_path / "ownership-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((tmp_path / "ownership-report.json").read_text(encoding="utf-8"))
        expected = ["SUCCESSOR_שלום"] if retired in ("same", "recreated") else [] if retired == "dispose" else ["OWNERSHIP_שלום"]
        assert [body["content"] for body in attempted] == expected
        assert len(stored) == len(expected)
        assert report["initialReads"] == (0 if retired in ("same", "recreated", "dispose") else 1)
        assert report["locationReads"] == (1 if phase == "caller" else 0)
        if retired not in ("dispose", "created"):
            assert ("ses_ownership_b" if retired == "other" else "ses_ownership_a") in closed
        client.app.state.pallium_service.drain_processing_queue(worker_id="ownership-history")
        for body, receipt in stored:
            assert body["thread_ref"] == "ses_ownership_a" and body["actor_ref"] == "ownership-actor"
            assert body["container_ref"] == "git:example.test/team/ownership"
            history = client.post("/query", json={"text": body["content"], "container_ref": body["container_ref"],
                "active_session_ref": body["thread_ref"], "thread_ref": body["thread_ref"],
                "actor_ref": body["actor_ref"], "visibility": "private", "trigger_origin": "agent_pull",
                "limit": 50, "source_only": True})
            assert history.status_code == 200 and receipt["source_item_id"] in history.text
            expanded = client.get("/source/" + receipt["source_item_id"] + "/context", params={
                "container_ref": body["container_ref"], "query_actor_ref": body["actor_ref"], "before": 0, "after": 0})
            assert expanded.status_code == 200 and body["content"] in expanded.text
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("lookup_rejected", [False, True], ids=["ordinary", "native-lookup-rejected"])
def test_ordinary_delivery_before_delayed_wake_preserves_custody_and_progress(client, tmp_path, lookup_rejected):
    """Real plugin/HTTP custody; native promotion and terminal events are controlled."""
    from tests.test_opencode_relay_wake_e2e import _setup, _send

    node, git = shutil.which("node"), shutil.which("git")
    assert node and git, "installed Node and Git are required; do not download runtimes"
    root = Path(__file__).resolve().parents[1]
    assert Path(create_app.__code__.co_filename).resolve().is_relative_to(root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}}
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "TEMP", "TMP"):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    subprocess.run([git, "init", "-q", str(workspace)], env=env, check=True, timeout=10)
    subprocess.run([git, "-C", str(workspace), "remote", "add", "origin",
                    "https://example.test/team/relay.git"], env=env, check=True, timeout=10)
    base = _setup(client, session="ses_obsolete_wake", location=str(workspace), enroll=False)
    anchor = _send(client, base, "ANCHOR_שלום_界").json()
    later = []
    requests = []

    class JourneyHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/fixture/later":
                response = _send(client, base, "LATER_界_שלום")
                assert response.is_success, response.text
                later.append(response.json())
            else:
                response = client.request(self.command, self.path, content=raw or None,
                                          headers={"Content-Type": "application/json"})
            requests.append({"method": self.command, "path": self.path,
                             "body": json.loads(raw) if raw else None,
                             "status": response.status_code, "result": response.json()})
            payload = response.content
            try:
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), JourneyHTTP)
    assert server.server_port != 19836
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    program = tmp_path / "obsolete-wake-caller.mjs"
    program.write_text(r"""import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {writeFileSync} from 'node:fs';
const cwd=process.env.JOURNEY_DIRECTORY,sessionID='ses_obsolete_wake';
const origin='http://localhost:'+process.env.PALLIUM_PORT;
const anchor=JSON.parse(process.env.JOURNEY_ANCHOR),scope={container_ref:'git:example.test/team/relay'};
const savedFetch=globalThis.fetch,savedSpawn=childProcess.spawn,children=[],calls=[],prompts=[],history=[],hooks={},disposed=[];
const defer=()=>{let resolve;const promise=new Promise(done=>resolve=done);return{promise,resolve}};
const promotion=defer(),jobs=[],logs=[],issued=[];
let tick,cleanup,failedContext,terminal=0,waits=0,interrupts=0,rejectLookup=false;
const lookupRejected=defer();
const pause=()=>new Promise(resolve=>setImmediate(resolve));
const until=async(check,label)=>{
 const end=Date.now()+8000;
 while(!check()){assert.ok(Date.now()<end,label+': '+JSON.stringify(logs));await new Promise(resolve=>setTimeout(resolve,5))}
 await pause();
};
// Same owned-child/close pattern as withGitProcess; no replacement Git or shell.
childProcess.spawn=(command,args,options)=>{
 assert.equal(command,'git');assert.equal(options.cwd,cwd);assert.ok(!options.shell);
 assert.ok([['remote','get-url','origin'],['rev-list','--max-parents=0','HEAD'],['config','user.name']]
  .some(allowed=>JSON.stringify(allowed)===JSON.stringify(args)));
 const child=savedSpawn(process.env.JOURNEY_GIT,args,options),entry={child,done:false};
 entry.closed=new Promise(resolve=>child.once('close',()=>{entry.done=true;resolve()}));
 children.push(entry);return child;
};
syncBuiltinESMExports();
globalThis.fetch=async(input,init={})=>{
 const url=new URL(typeof input==='string'?input:input.url);
 assert.equal(url.origin,origin,'only the fixture-owned loopback port is permitted');
 const body=init.body?JSON.parse(init.body):null;
 issued.push({path:url.pathname,operation:body?.operation});
 const response=await savedFetch(input,{...init,redirect:'error'});
 const result=await response.clone().json();
 calls.push({path:url.pathname,body,status:response.status,result});
 if(body?.operation==='terminal'&&response.ok)terminal++;
 return response;
};
globalThis.setInterval=(fn)=>{tick=fn;return{unref(){}}};
globalThis.clearInterval=()=>{};
const request=async(method,path,body)=>{
 const response=await fetch(origin+path,{method,headers:{'Content-Type':'application/json'},
  ...(body?{body:JSON.stringify(body)}:{})});
 assert.equal(response.status,200,await response.clone().text());return response.json();
};
const status=async(message)=>(await request('GET','/relay/messages/'+message.message_id+'?'+new URLSearchParams(scope))).deliveries[0];
const acks=()=>calls.filter(c=>c.path==='/relay/deliveries/ack');
const turns=()=>calls.filter(c=>c.path==='/relay/turn');
const ctx={location:{directory:cwd},app:{log:entry=>logs.push(entry.message)},session:{
 hook:async(name,fn)=>{hooks[name]=fn;return{dispose:()=>disposed.push(name)}},
 get:async({sessionID:id})=>{
  if(rejectLookup){rejectLookup=false;lookupRejected.resolve();throw new Error('native lookup unavailable')}
  return{id,location:{directory:cwd},revert:null};
 },
 context:async()=>({data:history}),
 prompt:input=>{
  prompts.push(input);
  const work=(async()=>{
   assert.equal(input.delivery,'queue');assert.equal(input.sessionID,sessionID);
   if(prompts.length===1)await promotion.promise;
   history.push({type:'user',id:input.id,text:input.text,metadata:input.metadata});
   await hooks.prompt({sessionID,messageID:input.id,prompt:{text:input.text},metadata:input.metadata});
   const user={id:input.id,role:'user',content:[{type:'text',text:input.text}],metadata:input.metadata};
   const before={acks:acks().length,turns:turns().length};
   let error;
   try{await hooks.context({sessionID,messages:[user]})}catch(caught){error=caught}
   if(prompts.length===1){
     assert.equal(error?.message,`Pallium wake context response has no matching delivery (delivery_id=${input.metadata.delivery_id})`);
    assert.equal(user.content.length,1,'unowned delivered payload must not enter model context');
    assert.equal(acks().length,before.acks);assert.equal(turns().length,before.turns);
    failedContext={error:error.message,acks:before.acks,turns:before.turns};
   }else{
    assert.ifError(error);assert.match(user.content.at(-1).text,/LATER_界_שלום/);
    assert.doesNotMatch(user.content.at(-1).text,/ANCHOR_שלום_界/);
    assert.equal(acks().length,before.acks+1);
   }
   // Controlled native boundary turns the actual context result into its idle event.
   history.push({type:'idle',id:'msg_native_terminal_'+prompts.length,
    outcome:error?'failed':'succeeded',...(error?{error:{message:error.message}}:{})});
   return{id:input.id};
  })();
  jobs.push(work);return work;
 },
 wait:async()=>{waits++;assert.equal(history.at(-1)?.type,'idle')},
 interrupt:async()=>{interrupts++},
},event:{subscribe:async function*({signal}){
 if(!signal.aborted)await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
}}};
let watchdog,report;
try{
 const {default:production}=await import(process.env.JOURNEY_PLUGIN);
 cleanup=await production.setup(ctx);
 await Promise.race([(async()=>{
  await until(()=>calls.some(c=>c.body?.operation==='enroll'&&c.status===200),'startup enrollment');
  tick();await until(()=>prompts.length===1,'reserved native input queued');
  const first=prompts[0],reservation=calls.find(c=>c.body?.operation==='poll'&&c.result.wake)?.result.wake;
  assert.equal(reservation.delivery_id,anchor.deliveries[0].delivery_id);
  assert.equal(first.id,reservation.native_input_id);
  assert.equal(first.metadata.generation,reservation.generation);
  assert.equal(first.metadata.delivery_id,reservation.delivery_id);
  const pending=await status(anchor);assert.equal(pending.state,'pending');assert.equal(pending.attempts,0);
  assert.equal(history.some(row=>row.id===first.id),false,'native promotion gate must still hold');
  const ordinary={id:'msg_ordinary',role:'user',content:[{type:'text',text:'ordinary fixture task'}]};
  history.push({type:'user',id:ordinary.id,text:ordinary.content[0].text});
  await hooks.prompt({sessionID,messageID:ordinary.id,prompt:{text:ordinary.content[0].text}});
  await hooks.context({sessionID,messages:[ordinary]});
  assert.match(ordinary.content.at(-1).text,/ANCHOR_שלום_界/);
  const delivered=await status(anchor);
  assert.equal(delivered.state,'delivered');assert.equal(delivered.attempts,1);
  assert.equal(acks().length,1);assert.equal(turns().length,1);
  assert.equal(history.some(row=>row.id===first.id),false,'public ACK must precede native promotion');
  promotion.resolve();
  await until(()=>terminal===1,'failed native terminal reconciliation');
   assert.equal(failedContext.error,`Pallium wake context response has no matching delivery (delivery_id=${reservation.delivery_id})`);
  const context=calls.find(c=>c.body?.operation==='context'&&c.body.delivery_id===reservation.delivery_id);
  assert.equal(context.status,200);assert.deepEqual(context.result.deliveries,[]);
  assert.equal(context.result.restored,false);
  const finished=calls.find(c=>c.body?.operation==='terminal');
  assert.equal(finished.body.generation,reservation.generation);
  assert.equal(finished.body.native_input_id,first.id);
  assert.equal(finished.body.delivery_id,reservation.delivery_id);
  assert.equal(finished.body.terminal_message_id,'msg_native_terminal_1');
  assert.equal(finished.result.wake.terminal,true);
  const pollBoundary=calls.length;tick();
  await until(()=>calls.slice(pollBoundary).some(c=>c.body?.operation==='poll'&&c.result.wake===null),'anchor release');
  const later=await request('POST','/fixture/later',{});
  const lookupBoundary=issued.length;
  if(process.env.JOURNEY_REJECT_LOOKUP==='1'){
   rejectLookup=true;tick();
   await lookupRejected.promise;await pause();
   assert.deepEqual(issued.slice(lookupBoundary),[],'unknown ownership must not cause a backend request');
   const pending=await status(later);
   assert.equal(pending.state,'pending');assert.equal(pending.attempts,0);
  }
  tick();await until(()=>terminal===2,'later independent native delivery and terminal');
  const progressed=await status(later),unchanged=await status(anchor);
  assert.equal(progressed.state,'delivered');assert.equal(progressed.attempts,1);
  assert.deepEqual(unchanged,delivered,'obsolete wake must not mutate the delivered source');
  assert.equal(prompts.length,2);assert.notEqual(prompts[0].id,prompts[1].id);
  assert.equal(acks().length,2);assert.equal(turns().length,1);
  if(process.env.JOURNEY_REJECT_LOOKUP==='1'){
   assert.ok(!issued.slice(lookupBoundary).some(c=>['enroll','detach'].includes(c.operation)));
   const poll=calls.find(c=>c.body?.operation==='poll'&&c.result.wake?.delivery_id===later.deliveries[0].delivery_id);
   assert.equal(poll.body.owner_id,finished.body.owner_id);
   assert.equal(prompts[1].id,poll.result.wake.native_input_id);
  }
  assert.equal(waits,2);assert.equal(interrupts,0);
  report={characterization:true,native_boundary:'controlled, not installed-host proof',
   beforePromotion:delivered,anchorAfter:unchanged,laterAfter:progressed,failedContext,
   nativeIDs:prompts.map(p=>p.id),terminalRequests:calls.filter(c=>c.body?.operation==='terminal')};
 })(),new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(new Error('owned journey exceeded 45 seconds')),45000)})]);
}finally{
 clearTimeout(watchdog);promotion.resolve();await cleanup?.();
 await Promise.allSettled(jobs);
 for(const {child} of children)if(child.exitCode===null&&child.signalCode===null)child.kill();
 await Promise.all(children.map(entry=>entry.closed));
 writeFileSync(process.env.JOURNEY_REPORT,JSON.stringify({report,logs,
  cleanup:{pluginDisposed:disposed.length===3,nativeJobsJoined:true,gitChildrenClosed:children.filter(e=>e.done).length},
  http:calls}));
 assert.ok(children.every(entry=>entry.done),'owned Git children must close, not merely exit');
 assert.deepEqual(disposed.sort(),['compaction','context','prompt']);
}
""", encoding="utf-8")
    env.update(PALLIUM_PORT=str(server.server_port), PALLIUM_HOOK_ACTOR_REF="fixture-actor",
               JOURNEY_PLUGIN=(root / "integrations/opencode/.opencode/plugins/pallium-v2.mjs").as_uri(),
               JOURNEY_GIT=git, JOURNEY_DIRECTORY=str(workspace),
               JOURNEY_REPORT=str(tmp_path / "journey-report.json"), JOURNEY_ANCHOR=json.dumps(anchor),
               JOURNEY_REJECT_LOOKUP="1" if lookup_rejected else "0")
    try:
        result = subprocess.run([node, str(program)], env=env, cwd=workspace, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=75)
        (tmp_path / "journey-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        (tmp_path / "journey-http.json").write_text(json.dumps(requests), encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((tmp_path / "journey-report.json").read_text(encoding="utf-8"))
        assert report["report"]["characterization"] is True
        assert len(later) == 1
        assert report["report"]["beforePromotion"]["delivery_id"] == anchor["deliveries"][0]["delivery_id"]
        assert report["report"]["laterAfter"]["delivery_id"] == later[0]["deliveries"][0]["delivery_id"]
        assert report["cleanup"]["gitChildrenClosed"] > 0
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        (tmp_path / "journey-cleanup.json").write_text(json.dumps({
            "listener_closed": server.fileno() == -1, "server_thread_joined": not thread.is_alive(),
        }), encoding="utf-8")
        assert not thread.is_alive() and server.fileno() == -1, "fixture listener must drain"


@pytest.mark.parametrize("ack_fault", ["precommit", "postcommit"])
def test_emitted_ack_faults_preserve_registered_reply_and_progress(client, tmp_path, monkeypatch, ack_fault):
    """Production context/ACK and registered MCP share the same real isolated app."""
    import asyncio
    from datetime import datetime, timezone
    import httpx
    from mcp.server.fastmcp.exceptions import ToolError
    from app.mcp.server import create_server
    import storage.sqlite_relay as relay_store
    from tests.test_opencode_relay_wake_e2e import _setup, _send, SCOPE
    from tests.test_relay_mcp_tools import bind_asgi_post, tool_error_payload

    node, git = shutil.which("node"), shutil.which("git")
    assert node and git, "installed runtimes are required"
    root = Path(__file__).resolve().parents[1]
    assert Path(create_app.__code__.co_filename).resolve().is_relative_to(root)
    normalize, clock = relay_store._now, [datetime.now(timezone.utc)]
    monkeypatch.setattr(relay_store, "_now", lambda value=None: normalize(value) if value is not None else clock[0])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}}
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "TEMP", "TMP"):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    subprocess.run([git, "init", "-q", str(workspace)], env=env, check=True, timeout=10)
    subprocess.run([git, "-C", str(workspace), "remote", "add", "origin",
                    "https://example.test/team/relay.git"], env=env, check=True, timeout=10)
    base = _setup(client, session="ses_ack_fault", location=str(workspace), enroll=False)
    anchor = _send(client, base, "ANCHOR_שלום_界").json()
    faults, requests, mcp_posts = [], [], []

    async def asgi_post(path, payload):
        assert path == "/relay/replies" and "receipt" not in payload
        assert not {"runtime", "session_ref", "sender_runtime", "sender_session_ref"} & payload.keys()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                     base_url="http://fixture", timeout=30) as http:
            response = await http.post(path, json=payload)
            mcp_posts.append({"path": path, "body": payload, "status": response.status_code,
                              "result": response.json()})
            response.raise_for_status()
            return response.json()

    # Existing tool-layer binding, not a replacement tool or invented caller metadata.
    bind_asgi_post(monkeypatch, asgi_post)
    registered = create_server()

    class AckHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, body):
            requests.append({"path": self.path, "body": body, "status": status, "result": value})
            payload = json.dumps(value).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.loads(raw) if raw else None
            if self.path == "/fixture/mcp":
                try:
                    content, _ = asyncio.run(registered.call_tool("pallium_relay_reply", {
                        "delivery_id": anchor["deliveries"][0]["delivery_id"],
                        "message": "ANSWER_שלום_界", **SCOPE,
                    }))
                    result = {"result": json.loads(content[0].text)}
                except ToolError as error:
                    result = {"error": tool_error_payload(str(error))}
                return self.respond(200, result, body)
            if self.path == "/fixture/advance":
                clock[0] += timedelta(seconds=61)
                return self.respond(200, {"advanced_seconds": 61}, body)
            if self.path == "/fixture/later":
                response = _send(client, base, "LATER_界_שלום")
                return self.respond(response.status_code, response.json(), body)
            owned_ack = (self.path == "/relay/deliveries/ack" and
                         body["delivery_id"] == anchor["deliveries"][0]["delivery_id"] and not faults)
            if owned_ack and ack_fault == "precommit":
                value = {"detail": {"code": "relay_busy", "retryable": True}}
                faults.append({"stage": "precommit", "route_executed": False, "status": 503, "result": value})
                return self.respond(503, value, body)
            response = client.request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if owned_ack:
                assert response.status_code == 200 and response.json()["state"] == "delivered"
                faults.append({"stage": "postcommit", "route_executed": True,
                               "status": response.status_code, "result": response.json(),
                               "response_delivered": False})
                requests.append({"path": self.path, "body": body, **faults[-1]})
                self.close_connection = True  # Real route committed; no HTTP response reaches the hook.
                return
            self.respond(response.status_code, response.json(), body)

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), AckHTTP)
    assert server.server_port != 19836
    monkeypatch.setenv("PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", SCOPE["container_ref"])
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    program = tmp_path / "ack-fault-caller.mjs"
    program.write_text(r"""import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const cwd=process.env.ACK_DIRECTORY,mode=process.env.ACK_FAULT,sessionID='ses_ack_fault';
const anchor=JSON.parse(process.env.ACK_ANCHOR),id=anchor.deliveries[0].delivery_id;
const origin='http://localhost:'+process.env.PALLIUM_PORT,scope={container_ref:'git:example.test/team/relay'};
const savedFetch=globalThis.fetch,savedSpawn=childProcess.spawn,calls=[],children=[],hooks={},disposed=[],logs=[];
const completed=new Set();let current,emittedBeforeAck=false,cleanup,report,watchdog;
childProcess.spawn=(command,args,options)=>{
 assert.equal(command,'git');assert.equal(options.cwd,cwd);assert.ok(!options.shell);
 assert.ok([['remote','get-url','origin'],['rev-list','--max-parents=0','HEAD'],['config','user.name']]
  .some(allowed=>JSON.stringify(allowed)===JSON.stringify(args)));
 const child=savedSpawn(process.env.ACK_GIT,args,options),entry={child,done:false};
 entry.closed=new Promise(resolve=>child.once('close',()=>{entry.done=true;resolve()}));
 children.push(entry);return child;
};
syncBuiltinESMExports();
globalThis.fetch=async(input,init={})=>{
 const url=new URL(typeof input==='string'?input:input.url);assert.equal(url.origin,origin);
 const body=init.body?JSON.parse(init.body):null;
 if(url.pathname==='/relay/deliveries/ack'&&body.delivery_id===id&&!emittedBeforeAck){
  assert.match(current.content.at(-1).text,/ANCHOR_שלום_界/);emittedBeforeAck=true;
 }
 const entry={path:url.pathname,body};calls.push(entry);
 try{
  const response=await savedFetch(input,{...init,redirect:'error'});
  entry.status=response.status;entry.result=await response.clone().json();return response;
 }catch(error){entry.error=String(error);throw error}
};
globalThis.setInterval=()=>({unref(){}});globalThis.clearInterval=()=>{};
const request=async(method,path,body,expected=200)=>{
 const response=await fetch(origin+path,{method,headers:{'Content-Type':'application/json'},
  ...(body?{body:JSON.stringify(body)}:{})});
 assert.equal(response.status,expected,await response.clone().text());return response.json();
};
const status=async(message)=>(await request('GET','/relay/messages/'+message.message_id+'?'+new URLSearchParams(scope))).deliveries[0];
const ackCalls=()=>calls.filter(c=>c.path==='/relay/deliveries/ack');
const ctx={location:{directory:cwd},app:{log:entry=>logs.push(entry.message)},session:{
 hook:async(name,fn)=>{hooks[name]=fn;return{dispose:()=>disposed.push(name)}},
 get:async({sessionID:id})=>({id,location:{directory:cwd},revert:null}),
 context:async()=>({data:[]}),
},event:{subscribe:async function*({signal}){
 if(!signal.aborted)await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
}}};
const context=async(input)=>{
 current={id:input,role:'user',content:[{type:'text',text:'ordinary fixture work'}]};
 await hooks.prompt({sessionID,messageID:input,prompt:{text:current.content[0].text}});
 await hooks.context({sessionID,messages:[current]});return current.content.at(-1).text;
};
try{
 const {default:production}=await import(process.env.ACK_PLUGIN);
 cleanup=await production.setup(ctx);
 await Promise.race([(async()=>{
  const first=await context('msg_first');
  assert.match(first,/ANCHOR_שלום_界/);assert.equal(emittedBeforeAck,true);
  completed.add(id); // Stand-in completed work; never execute it again on a genuine redelivery.
  assert.equal(ackCalls().length,1);
  const before=await status(anchor);
  assert.equal(before.state,mode==='precommit'?'claimed':'delivered');assert.equal(before.attempts,1);
  if(mode==='precommit'){
   assert.equal(ackCalls()[0].status,503);
   assert.deepEqual(ackCalls()[0].result,{detail:{code:'relay_busy',retryable:true}});
   const live=await request('POST','/fixture/mcp',{});
   assert.equal(live.error.status_code,409);
   assert.equal(live.error.detail.detail,'receipt required when replying from claimed state');
  }else{
   assert.ok(ackCalls()[0].error,'committed ACK response must actually be lost at the caller');
   assert.equal(ackCalls()[0].status,undefined);
  }
  assert.equal((await request('POST','/fixture/advance',{})).advanced_seconds,61);
  const reply=await request('POST','/fixture/mcp',{});
  const replyID='relay-reply-'+createHash('sha256').update(id).digest('hex');
  if(mode==='precommit'){
   assert.equal(reply.error.status_code,409);assert.equal(reply.error.detail.detail,'claim lease has expired');
   await request('GET','/relay/messages/'+replyID+'?'+new URLSearchParams(scope),null,404);
  }else{
   assert.equal(reply.result.message_id,replyID);assert.equal(reply.result.deliveries.length,1);
   const saved=await request('GET','/relay/messages/'+replyID+'?'+new URLSearchParams(scope));
   assert.equal(saved.payload,'ANSWER_שלום_界');assert.equal(saved.in_reply_to,anchor.message_id);
  }
  const next=await context('msg_genuine_next');
  const recovered=await status(anchor);
  if(mode==='precommit'){
   assert.match(next,/ANCHOR_שלום_界/);
   assert.match(next,/claim_attempt: 2\npossible_redelivery: true/);
   assert.equal(completed.has(id),true,'skip the previously completed action');
   assert.equal(recovered.attempts,2);assert.equal(ackCalls().length,2);
  }else{
   assert.doesNotMatch(next,/ANCHOR_שלום_界/);
   assert.equal(recovered.attempts,1);assert.equal(ackCalls().length,1);
  }
  assert.equal(recovered.state,'delivered');assert.equal(completed.size,1);
  const later=await request('POST','/fixture/later',{});
  assert.match(await context('msg_later_independent'),/LATER_界_שלום/);
  completed.add(later.deliveries[0].delivery_id);
  const progressed=await status(later);
  assert.equal(progressed.state,'delivered');assert.equal(progressed.attempts,1);
  assert.equal(completed.size,2);assert.equal(ackCalls().length,mode==='precommit'?3:2);
  report={mode,emittedBeforeAck,before,recovered,progressed,reply,
   completedDistinctActions:completed.size,ackCalls:ackCalls()};
 })(),new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(new Error('owned ACK control exceeded 45 seconds')),45000)})]);
}finally{
 clearTimeout(watchdog);await cleanup?.();
 for(const {child} of children)if(child.exitCode===null&&child.signalCode===null)child.kill();
 await Promise.all(children.map(entry=>entry.closed));
 writeFileSync(process.env.ACK_REPORT,JSON.stringify({report,logs,http:calls,
  cleanup:{pluginDisposed:disposed.length===3,gitChildrenClosed:children.filter(e=>e.done).length}}));
 assert.ok(children.every(e=>e.done));assert.deepEqual(disposed.sort(),['compaction','context','prompt']);
}
""", encoding="utf-8")
    env.update(PALLIUM_PORT=str(server.server_port), PALLIUM_HOOK_ACTOR_REF="fixture-actor",
               ACK_PLUGIN=(root / "integrations/opencode/.opencode/plugins/pallium-v2.mjs").as_uri(),
               ACK_GIT=git, ACK_DIRECTORY=str(workspace), ACK_FAULT=ack_fault,
               ACK_REPORT=str(tmp_path / "ack-report.json"), ACK_ANCHOR=json.dumps(anchor))
    try:
        result = subprocess.run([node, str(program)], env=env, cwd=workspace, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=75)
        (tmp_path / "ack-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        (tmp_path / "ack-http.json").write_text(json.dumps({"faults": faults, "requests": requests,
                                                         "registered_mcp_posts": mcp_posts}), encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((tmp_path / "ack-report.json").read_text(encoding="utf-8"))
        assert len(faults) == 1 and faults[0]["stage"] == ack_fault
        assert len(mcp_posts) == (2 if ack_fault == "precommit" else 1)
        assert [p["status"] for p in mcp_posts] == ([409, 409] if ack_fault == "precommit" else [200])
        assert report["report"]["completedDistinctActions"] == 2
        assert report["cleanup"]["gitChildrenClosed"] > 0
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        (tmp_path / "ack-cleanup.json").write_text(json.dumps({
            "listener_closed": server.fileno() == -1, "server_thread_joined": not thread.is_alive(),
        }), encoding="utf-8")
        assert not thread.is_alive() and server.fileno() == -1


@pytest.mark.parametrize("ack_fault", ["precommit", "postcommit"])
def test_emitted_ack_maintenance_without_next_prompt(client, tmp_path, monkeypatch, ack_fault):
    """Actual production interval confirms only emitted custody during held work."""
    import asyncio
    from datetime import datetime, timezone
    import httpx
    from app.mcp.server import create_server
    from tests.test_relay_mcp_tools import bind_asgi_post
    from tests.test_opencode_relay_wake_e2e import _setup, _send, SCOPE
    import storage.sqlite_relay as relay_store

    node, git = shutil.which("node"), shutil.which("git")
    assert node and git
    root = Path(__file__).resolve().parents[1]
    assert Path(create_app.__code__.co_filename).resolve().is_relative_to(root)
    normalize, clock = relay_store._now, [datetime.now(timezone.utc)]
    monkeypatch.setattr(relay_store, "_now", lambda value=None: normalize(value) if value is not None else clock[0])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}}
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "TEMP", "TMP"):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    (tmp_path / "gitconfig").write_text("", encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    subprocess.run([git, "init", "-q", str(workspace)], env=env, check=True, timeout=10)
    subprocess.run([git, "-C", str(workspace), "remote", "add", "origin",
                    "https://example.test/team/relay.git"], env=env, check=True, timeout=10)
    base = _setup(client, session="ses_ack_maintenance", location=str(workspace), enroll=False)
    anchor = _send(client, base, "MAINTENANCE_שלום_界").json()
    faults, requests, mcp_posts = [], [], []

    async def asgi_post(path, payload):
        assert path == "/relay/replies" and "receipt" not in payload
        assert not {"runtime", "session_ref", "sender_runtime", "sender_session_ref"} & payload.keys()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                     base_url="http://fixture", timeout=30) as http:
            response = await http.post(path, json=payload)
            mcp_posts.append({"body": payload, "status": response.status_code, "result": response.json()})
            response.raise_for_status()
            return response.json()

    bind_asgi_post(monkeypatch, asgi_post)
    registered = create_server()

    class MaintenanceHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, body, retry_after=None):
            requests.append({"path": self.path, "body": body, "status": status, "result": value})
            payload = json.dumps(value).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                if retry_after is not None:
                    self.send_header("Retry-After", retry_after)
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.loads(raw) if raw else None
            if self.path == "/fixture/reply":
                content, _ = asyncio.run(registered.call_tool("pallium_relay_reply", {
                    "delivery_id": anchor["deliveries"][0]["delivery_id"], "message": "RESULT_שלום_界", **SCOPE,
                }))
                return self.respond(200, json.loads(content[0].text), body)
            if self.path == "/fixture/advance":
                clock[0] += timedelta(seconds=61)
                return self.respond(200, {"advanced_seconds": 61}, body)
            if self.path == "/fixture/later":
                response = _send(client, base, "LATER_MAINTENANCE_界")
                return self.respond(response.status_code, response.json(), body)
            owned_ack = (self.path == "/relay/deliveries/ack" and not faults and
                         body["delivery_id"] == anchor["deliveries"][0]["delivery_id"])
            if owned_ack and ack_fault == "precommit":
                faults.append({"stage": "precommit", "route_executed": False, "status": 503})
                return self.respond(503, {"detail": {"code": "relay_busy", "retryable": True}}, body, "1")
            response = client.request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if owned_ack:
                assert response.status_code == 200 and response.json()["state"] == "delivered"
                faults.append({"stage": "postcommit", "route_executed": True, "status": 200,
                               "response_delivered": False, "result": response.json()})
                requests.append({"path": self.path, "body": body, **faults[-1]})
                self.close_connection = True
                return
            self.respond(response.status_code, response.json(), body)

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), MaintenanceHTTP)
    assert server.server_port != 19836
    monkeypatch.setenv("PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", SCOPE["container_ref"])
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    program = tmp_path / "ack-maintenance.mjs"
    program.write_text(r"""import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const cwd=process.env.ACK_DIRECTORY,sessionID='ses_ack_maintenance',mode=process.env.ACK_FAULT;
const anchor=JSON.parse(process.env.ACK_ANCHOR),id=anchor.deliveries[0].delivery_id;
const origin='http://localhost:'+process.env.PALLIUM_PORT,scope={container_ref:'git:example.test/team/relay'};
const savedFetch=globalThis.fetch,savedSpawn=childProcess.spawn,calls=[],children=[],hooks={},disposed=[],native=[];
let current,cleanup,watchdog,emitted=false,completed=0,report;
let finish;const longWork=new Promise(resolve=>{finish=resolve}).then(()=>{completed++});
childProcess.spawn=(command,args,options)=>{
 assert.equal(command,'git');assert.equal(options.cwd,cwd);assert.ok(!options.shell);
 assert.ok([['remote','get-url','origin'],['rev-list','--max-parents=0','HEAD'],['config','user.name']]
  .some(allowed=>JSON.stringify(allowed)===JSON.stringify(args)));
 const child=savedSpawn(process.env.ACK_GIT,args,options),entry={child,done:false};
 entry.closed=new Promise(resolve=>child.once('close',()=>{entry.done=true;resolve()}));children.push(entry);return child;
};syncBuiltinESMExports();
globalThis.fetch=async(input,init={})=>{
 const url=new URL(typeof input==='string'?input:input.url);assert.equal(url.origin,origin);
 const body=init.body?JSON.parse(init.body):null,entry={path:url.pathname,body,at:performance.now()};calls.push(entry);
 if(url.pathname==='/relay/deliveries/ack'&&body.delivery_id===id&&!emitted){
  assert.match(current.content.at(-1).text,/MAINTENANCE_שלום_界/);emitted=true;
 }
 try{
  const response=await savedFetch(input,{...init,redirect:'error'});
  entry.status=response.status;entry.result=await response.clone().json();return response;
 }catch(error){entry.error=String(error);throw error}
};
const request=async(method,path,body)=>{
 const response=await fetch(origin+path,{method,headers:{'Content-Type':'application/json'},
  ...(body?{body:JSON.stringify(body)}:{})});
 assert.equal(response.status,200,await response.clone().text());return response.json();
};
const status=async(message)=>(await request('GET','/relay/messages/'+message.message_id+'?'+new URLSearchParams(scope))).deliveries[0];
const acks=()=>calls.filter(c=>c.path==='/relay/deliveries/ack'&&c.body.delivery_id===id);
const ctx={location:{directory:cwd},app:{log(){}},session:{
 hook:async(name,fn)=>{hooks[name]=fn;return{dispose:()=>disposed.push(name)}},
 get:async({sessionID:id})=>({id,location:{directory:cwd},revert:null}),
 context:async()=>({data:[]}),prompt:async(input)=>{native.push(input);throw new Error('unexpected native input')},
 wait:async()=>longWork,
},event:{subscribe:async function*({signal}){
 if(!signal.aborted)await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
}}};
const context=async(input)=>{
 current={id:input,role:'user',content:[{type:'text',text:'ordinary long-running work'}]};
 await hooks.prompt({sessionID,messageID:input,prompt:{text:current.content[0].text}});
 await hooks.context({sessionID,messages:[current]});return current.content.at(-1).text;
};
try{
 const {default:production}=await import(process.env.ACK_PLUGIN);
 cleanup=await production.setup(ctx);
 await Promise.race([(async()=>{
  const text=await context('msg_long_work'),original=JSON.stringify(current);
  assert.match(text,/MAINTENANCE_שלום_界/);assert.equal(emitted,true);assert.equal(acks().length,1);
  const before=await status(anchor);
  assert.equal(before.state,mode==='precommit'?'claimed':'delivered');assert.equal(before.attempts,1);
  if(mode==='precommit')assert.equal(acks()[0].status,503);
  else assert.ok(acks()[0].error,'actual committed response loss');
  // Only real existing interval callbacks run while this original work is held.
  const deadline=performance.now()+12000;
  while(acks().length<2||!acks()[1].result){
   assert.ok(performance.now()<deadline,'existing lifecycle did not confirm the emitted receipt');
   await new Promise(resolve=>setTimeout(resolve,25));
  }
  const recovered=await status(anchor);
  assert.equal(recovered.state,'delivered');assert.equal(recovered.attempts,1);
  assert.deepEqual(acks()[1].body,acks()[0].body);
  assert.equal(acks()[1].status,200);assert.equal(acks()[1].result.already_delivered,mode==='postcommit');
  if(mode==='precommit')assert.ok(acks()[1].at-acks()[0].at>=1000,'Retry-After must hold');
  assert.equal(completed,0);assert.equal(JSON.stringify(current),original,'maintenance cannot change model context');
  assert.equal(calls.filter(c=>c.path==='/relay/turn').length,1,'no next prompt or new claim');
  assert.equal(native.length,0,'no native/action replay');
  await request('POST','/fixture/advance',{});
  finish();await longWork;assert.equal(completed,1);
  const reply=await request('POST','/fixture/reply',{});
  const replyID='relay-reply-'+createHash('sha256').update(id).digest('hex');
  assert.equal(reply.message_id,replyID);
  const saved=await request('GET','/relay/messages/'+replyID+'?'+new URLSearchParams(scope));
  assert.equal(saved.payload,'RESULT_שלום_界');assert.equal(saved.in_reply_to,anchor.message_id);
  const later=await request('POST','/fixture/later',{});
  assert.match(await context('msg_later_independent'),/LATER_MAINTENANCE_界/);
  const progressed=await status(later);assert.equal(progressed.state,'delivered');assert.equal(progressed.attempts,1);
  report={mode,before,recovered,progressed,reply,completed,acks:acks(),native};
 })(),new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(new Error('maintenance journey exceeded 30 seconds')),30000)})]);
}finally{
 clearTimeout(watchdog);finish();await longWork;await cleanup?.();
 for(const {child} of children)if(child.exitCode===null&&child.signalCode===null)child.kill();
 await Promise.all(children.map(entry=>entry.closed));
 writeFileSync(process.env.ACK_REPORT,JSON.stringify({report,http:calls,
  cleanup:{pluginDisposed:disposed.length===3,gitChildrenClosed:children.filter(e=>e.done).length}}));
 assert.ok(children.every(e=>e.done));assert.deepEqual(disposed.sort(),['compaction','context','prompt']);
}
""", encoding="utf-8")
    env.update(PALLIUM_PORT=str(server.server_port), PALLIUM_HOOK_ACTOR_REF="fixture-actor",
               ACK_PLUGIN=(root / "integrations/opencode/.opencode/plugins/pallium-v2.mjs").as_uri(),
               ACK_GIT=git, ACK_DIRECTORY=str(workspace), ACK_FAULT=ack_fault,
               ACK_REPORT=str(tmp_path / "maintenance-report.json"), ACK_ANCHOR=json.dumps(anchor))
    try:
        result = subprocess.run([node, str(program)], env=env, cwd=workspace, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=45)
        (tmp_path / "maintenance-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((tmp_path / "maintenance-report.json").read_text(encoding="utf-8"))
        assert len(faults) == 1 and faults[0]["stage"] == ack_fault
        assert len(mcp_posts) == 1 and mcp_posts[0]["status"] == 200
        assert report["report"]["completed"] == 1
        assert report["cleanup"]["pluginDisposed"] and report["cleanup"]["gitChildrenClosed"] > 0
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        (tmp_path / "maintenance-http.json").write_text(json.dumps({
            "faults": faults, "requests": requests, "registered_mcp_posts": mcp_posts,
        }), encoding="utf-8")
        (tmp_path / "maintenance-cleanup.json").write_text(json.dumps({
            "listener_closed": server.fileno() == -1, "server_thread_joined": not thread.is_alive(),
        }), encoding="utf-8")
        assert not thread.is_alive() and server.fileno() == -1


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_same_input_wake_context_recovers_stale_registration(
    client, tmp_path, monkeypatch, relay_admission_clock,
):
    _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, "delivered")


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_same_input_wake_continues_before_admission_report(
    client, tmp_path, monkeypatch, relay_admission_clock,
):
    _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, "admission-pending")


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_same_input_wake_context_recovers_after_outage(
    client, tmp_path, monkeypatch, relay_admission_clock,
):
    _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, "outage")


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
@pytest.mark.parametrize("fault", ["http503", "transport", "startup", "early-ack-http503"])
def test_same_pending_wake_context_resumes_two_tools_after_outage(
    client, tmp_path, monkeypatch, relay_admission_clock, fault,
):
    _same_input_wake_context_journey(
        client, tmp_path, monkeypatch, relay_admission_clock, "outage-recover-" + fault,
    )


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_context_bootstrap_restores_admitted_wake_after_local_reload(
    client, tmp_path, monkeypatch, relay_admission_clock,
):
    _same_input_wake_context_journey(
        client, tmp_path, monkeypatch, relay_admission_clock, "bootstrap-restored",
    )


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_context_recovery_preserves_replacement_owner(client, tmp_path, monkeypatch, relay_admission_clock):
    _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, "competing-owner")


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
@pytest.mark.parametrize("state", ["terminal", "rotated"])
def test_context_recovery_rejects_obsolete_backend_context(client, tmp_path, monkeypatch, relay_admission_clock, state):
    _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, state)


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
@pytest.mark.parametrize("expiry", ["lease", "ttl"])
def test_context_recovery_does_not_renew_unconfirmed_context(client, tmp_path, monkeypatch, relay_admission_clock, expiry):
    _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, expiry)


def _same_input_wake_context_journey(client, tmp_path, monkeypatch, relay_admission_clock, scenario):
    """Real plugin/HTTP; native ownership and backend time are controlled boundaries."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.main import _StartupGate
    import storage.sqlite_relay as sqlite_relay
    import socket
    from tests.test_opencode_relay_wake_e2e import _setup, _send

    node, git = shutil.which("node"), shutil.which("git")
    assert node and git, "use existing runtimes, never download a test prerequisite"
    root = Path(__file__).resolve().parents[1]
    assert Path(create_app.__code__.co_filename).resolve().is_relative_to(root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}}
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "TEMP", "TMP"):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    subprocess.run([git, "init", "-q", str(workspace)], env=env, check=True, timeout=10)
    subprocess.run([git, "-C", str(workspace), "remote", "add", "origin",
                    "https://example.test/team/relay.git"], env=env, check=True, timeout=10)
    real_now = sqlite_relay._now
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: real_now(value) if value is not None else clock[0])
    base = _setup(client, session="ses_repeat_context", location=str(workspace),
                  relay_admission_clock=relay_admission_clock, enroll=False)
    sent = _send(client, base, "CONTINUITY_שלום_界", expires_in_seconds=60 if scenario == "ttl" else 86400,
                 relay_admission_clock=relay_admission_clock)
    assert sent.status_code == 200, sent.text
    anchor, requests, later, controls = sent.json(), [], [], []
    controlled = False
    outage_active, outage_observed = threading.Event(), threading.Event()
    outage_faults, tool_actions = [], []
    recovery_journey = scenario.startswith("outage-recover-")
    hide_discovery = False
    startup = (TestClient(_StartupGate(client.app, SimpleNamespace(_initialized_app=None)))
               if scenario == "outage-recover-startup" else None)

    def control(body):
        nonlocal controlled
        controlled = True
        owner = {key: body[key] for key in ("session_ref", "container_ref", "endpoint_id",
                                           "scope_generation", "native_location", "owner_id")}
        if scenario == "competing-owner":
            owner["owner_id"] = "opencode-owner-" + "f" * 32
        renewed = client.post("/relay/opencode/wake", json={**owner, "operation": "enroll"})
        controls.append({"operation": "enroll", "status": renewed.status_code, "result": renewed.json()})
        assert renewed.status_code == 200, renewed.text
        if scenario in ("terminal", "rotated"):
            terminal = client.post("/relay/opencode/wake", json={**owner, "operation": "terminal",
                **{key: body[key] for key in ("generation", "delivery_id", "native_input_id")},
                "terminal_message_id": "msg_control_terminal"})
            controls.append({"operation": "terminal", "status": terminal.status_code, "result": terminal.json()})
            assert terminal.status_code == 200, terminal.text
            if scenario == "rotated":
                clock[0] += timedelta(seconds=3)
                queued = _send(client, base, "OBSOLETE_SUCCESSOR_界")
                assert queued.status_code == 200, queued.text
                rotated = client.post("/relay/opencode/wake", json={**owner, "operation": "poll"})
                controls.append({"operation": "poll", "status": rotated.status_code, "result": rotated.json()})
                assert rotated.status_code == 200, rotated.text
                assert rotated.json()["wake"]["generation"] > body["generation"]

    class JourneyHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            nonlocal hide_discovery
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.loads(raw) if raw else None
            outage_response = (scenario.startswith("outage") and outage_active.is_set()
                               and self.path == "/relay/opencode/wake" and body
                               and body.get("operation") == "context")
            if self.path == "/fixture/bootstrap" and scenario == "bootstrap-restored":
                hide_discovery = True
                payload, status = b'{"hide_next_discovery":true}', 200
            elif self.path.startswith("/relay/sessions?") and hide_discovery:
                hide_discovery = False
                payload, status = b"[]", 200
            elif self.path == "/fixture/outage" and scenario.startswith("outage"):
                assert not outage_active.is_set() and not outage_observed.is_set()
                outage_active.set()
                payload, status = b'{"outage":"armed"}', 200
            elif self.path == "/fixture/tool" and (scenario.startswith("outage") or scenario == "admission-pending"):
                assert body["step"] in (("completed-first-step", "completed-second-step")
                            if recovery_journey or scenario == "admission-pending" else ("completed-first-step",))
                tool_actions.append(body["step"])
                payload, status = json.dumps(body).encode(), 200
            elif self.path == "/fixture/recover" and scenario.startswith("outage"):
                assert outage_active.is_set() and outage_observed.is_set()
                assert len(outage_faults) == (2 if recovery_journey else 1)
                outage_active.clear()
                payload, status = b'{"outage":"released-after-observed-context"}', 200
            elif outage_response:
                if startup is not None:
                    response = startup.post(self.path, json=body)
                    payload, status = response.content, response.status_code
                    assert status == 503 and response.json() == {"error": "service not initialized"}
                else:
                    payload = b'{"detail":{"code":"relay_busy","retryable":true}}'
                    status = None if scenario == "outage-recover-transport" else 503
            elif self.path == "/relay/deliveries/ack" and scenario in ("lease", "ttl"):
                payload, status = b'{"detail":{"code":"relay_busy","retryable":true}}', 503
            elif self.path == "/fixture/advance":
                assert body["seconds"] in (14, 16)
                clock[0] += timedelta(seconds=body["seconds"])
                payload, status = json.dumps({"now": clock[0].isoformat()}).encode(), 200
            else:
                if self.path == "/fixture/later":
                    response = _send(client, base, "FOLLOWUP_界_שלום")
                    if response.is_success:
                        later.append(response.json())
                else:
                    response = client.request(self.command, self.path, content=raw or None,
                                              headers={"Content-Type": "application/json"})
                payload, status = response.content, response.status_code
                if (not controlled and scenario in ("competing-owner", "terminal", "rotated")
                        and body and body.get("operation") == "context" and status == 409
                        and response.json().get("detail") == "OpenCode registration is missing or stale"):
                    control(body)
            requests.append({"method": self.command, "path": self.path, "body": body,
                             "status": status, "result": json.loads(payload),
                             "backend_time": clock[0].isoformat()})
            if outage_response:
                outage_faults.append({"status": status, "body": body})
                outage_observed.set()
                if status is None:
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("127.0.0.1", 0), JourneyHTTP)
    assert server.server_port != 19836
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    program = tmp_path / "repeat-context-caller.mjs"
    program.write_text(r"""import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {writeFileSync} from 'node:fs';
const cwd=process.env.JOURNEY_DIRECTORY,sessionID='ses_repeat_context';
const origin='http://localhost:'+process.env.PALLIUM_PORT;
const anchor=JSON.parse(process.env.JOURNEY_ANCHOR),scope={container_ref:'git:example.test/team/relay'};
const scenario=process.env.JOURNEY_SCENARIO,unconfirmed=['lease','ttl'].includes(scenario);
const recoveryJourney=scenario.startsWith('outage-recover-');
const earlyAck=scenario==='outage-recover-early-ack-http503';
const admissionPending=scenario==='admission-pending'||earlyAck;
const savedFetch=globalThis.fetch,savedSpawn=childProcess.spawn,children=[],calls=[],prompts=[],history=[],hooks={},disposed=[];
const defer=()=>{let resolve;const promise=new Promise(done=>resolve=done);return{promise,resolve}};
const nativeRelease=defer(),ownedEntered=defer(),ownedRelease=defer(),logs=[],contexts=[];
const promptRelease=defer();
let promptHeld=false;
const toolActions=[];
const originalPerformance=globalThis.performance;
let outageFailures=0,outageMono=1000;
let tick,cleanup,watchdog,activeUser,armOwned=false,waits=0,waitReturns=0,interrupts=0,report;
const pause=()=>new Promise(resolve=>setImmediate(resolve));
const until=async(check,label)=>{
 const end=Date.now()+8000;
 while(!check()){assert.ok(Date.now()<end,label+': '+JSON.stringify(logs));await new Promise(resolve=>setTimeout(resolve,5))}
 await pause();
};
// Reuse the existing owned Git process/close observer; no shell or replacement Git.
childProcess.spawn=(command,args,options)=>{
 assert.equal(command,'git');assert.equal(options.cwd,cwd);assert.ok(!options.shell);
 assert.ok([['remote','get-url','origin'],['rev-list','--max-parents=0','HEAD'],['config','user.name']]
  .some(allowed=>JSON.stringify(allowed)===JSON.stringify(args)));
 const child=savedSpawn(process.env.JOURNEY_GIT,args,options),entry={child,done:false};
 entry.closed=new Promise(resolve=>child.once('close',()=>{entry.done=true;resolve()}));
 children.push(entry);return child;
};
syncBuiltinESMExports();
globalThis.fetch=async(input,init={})=>{
 const url=new URL(typeof input==='string'?input:input.url);
 assert.equal(url.origin,origin,'only fixture-owned loopback HTTP is permitted');
 const body=init.body?JSON.parse(init.body):null;
 if(url.pathname==='/relay/deliveries/ack'){
  assert.ok(activeUser?.content.at(-1).text.includes(body.delivery_id));
  assert.match(activeUser.content.at(-1).text,/Lower-authority context/);
 }
  let response;
  try{response=await savedFetch(input,{...init,redirect:'error'})}
  catch(error){
   if(recoveryJourney&&url.pathname==='/relay/opencode/wake'&&body?.operation==='context'){
    calls.push({path:url.pathname,body,status:null,result:null,error:'headerless transport failure'});
    outageMono+=45000;
    if(++outageFailures===2)await request('POST','/fixture/recover',{});
   }
   throw error;
  }
  calls.push({path:url.pathname,body,status:response.status,result:await response.clone().json()});
  if(scenario.startsWith('outage')&&url.pathname==='/relay/opencode/wake'&&body?.operation==='context'&&response.status===503){
   // Release only after this caller has received the real isolated HTTP failure.
   if(recoveryJourney)outageMono+=45000;
   if(!recoveryJourney||++outageFailures===2)await request('POST','/fixture/recover',{});
  }
  return response;
};
globalThis.setInterval=(fn)=>{tick=fn;return{unref(){}}};
globalThis.clearInterval=()=>{};
const request=async(method,path,body)=>{
 const response=await fetch(origin+path,{method,headers:{'Content-Type':'application/json'},
  ...(body?{body:JSON.stringify(body)}:{})});
 assert.equal(response.status,200,await response.clone().text());return response.json();
};
const status=async(message)=>(await request('GET','/relay/messages/'+message.message_id+'?'+new URLSearchParams(scope))).deliveries[0];
const acks=()=>calls.filter(c=>c.path==='/relay/deliveries/ack');
const operations=op=>calls.filter(c=>c.body?.operation===op);
const heartbeat=async()=>{
 const before=operations('poll').length;tick();
 await until(()=>operations('poll').length>before,'poll completed while native wait held');
 return operations('poll').at(-1);
};
const ctx={location:{directory:cwd},app:{log:entry=>logs.push(entry.message)},session:{
 hook:async(name,fn)=>{hooks[name]=fn;return{dispose:()=>disposed.push(name)}},
 get:async({sessionID:id})=>{
  if(armOwned){armOwned=false;ownedEntered.resolve();await ownedRelease.promise}
  return{id,location:{directory:cwd},revert:null};
 },
 context:async()=>({data:history}),
 prompt:async input=>{
  assert.equal(input.delivery,'queue');assert.equal(input.sessionID,sessionID);
  prompts.push(input);history.push({type:'user',id:input.id,text:input.text,metadata:input.metadata});
   await hooks.prompt({sessionID,messageID:input.id,prompt:{text:input.text},metadata:input.metadata});
   if(admissionPending){promptHeld=true;await promptRelease.promise}
   return{id:input.id};
 },
 wait:async()=>{waits++;await nativeRelease.promise;waitReturns++},
 interrupt:async()=>{interrupts++},
},event:{subscribe:async function*({signal}){
 if(!signal.aborted)await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
}}};
const context=async(input,expected,payload='CONTINUITY_שלום_界')=>{
 const user={id:input.id,role:'user',content:[{type:'text',text:input.text}],metadata:input.metadata};
 const before=acks().length;activeUser=user;
 let error;
 try{await hooks.context({sessionID,messages:[user]})}catch(caught){error=caught}
 finally{activeUser=null}
 const last=operations('context').at(-1);
 contexts.push({input:input.id,error:error?.message??null,status:last?.status,
  response:last?.result,attached:user.content.length===2,acks:acks().length-before});
 if(expected==='refused'){
  assert.ok(error,'unsafe backend context must remain visibly refused');
  assert.equal(user.content.length,1);assert.equal(acks().length,before);
  }else if(expected!=='outage'){
  assert.ifError(error);assert.equal(last.status,200);
  assert.match(user.content.at(-1).text,new RegExp(payload));
  assert.equal(last.result.restored,expected==='restored');
  assert.equal(acks().length,before+(expected==='initial'?1:0));
   if(expected==='restored')assert.doesNotMatch(user.content.at(-1).text,/claim_token:/);
  }else if(!error){
   assert.match(user.content.at(-1).text,new RegExp(payload));
   assert.doesNotMatch(user.content.at(-1).text,/claim_token:/);
 }
 return last;
};
try{
 const {default:production}=await import(process.env.JOURNEY_PLUGIN);
 cleanup=await production.setup(ctx);
 await Promise.race([(async()=>{
  await until(()=>operations('enroll').some(c=>c.status===200),'startup enrollment');
  await heartbeat();await until(()=>admissionPending?promptHeld:waits===1,'exact native input promoted');
  const first=prompts[0],snapshot=operations('poll')[0].result.wake;
  assert.equal(prompts.length,1);assert.equal(first.id,snapshot.native_input_id);
  assert.equal(first.metadata.generation,snapshot.generation);
  assert.equal(first.metadata.delivery_id,anchor.deliveries[0].delivery_id);
  const initial=await context(first,'initial');
  const delivered=await status(anchor);
   assert.equal(delivered.state,unconfirmed?'claimed':'delivered');assert.equal(delivered.attempts,1);
   assert.equal(acks().length,1);assert.equal(waitReturns,0);
   if(admissionPending){
     assert.equal(operations('admitted').length,0);
     assert.equal(initial.result.wake.admitted,false);
    }
    if(earlyAck){
     promptRelease.resolve();
     await until(()=>waits===1,'admission reported after local ACK');
     assert.equal(operations('admitted').length,1);
     assert.equal(operations('admitted')[0].result.wake.admitted,true);
     const polled=await heartbeat();
     assert.equal(polled.result.wake.admitted,true);
     assert.equal(polled.result.wake.native_input_id,first.id);
     assert.equal(operations('context').length,1,'no intervening successful restore');
    }
    if(scenario==='admission-pending'){
    await request('POST','/fixture/tool',{step:'completed-first-step'});
    const next=await context(first,'outage');
    assert.equal(next.status,200);
    assert.equal(next.result.restored,true);
    assert.equal(next.result.wake.admitted,false);
    assert.equal(next.result.deliveries[0].delivery_id,delivered.delivery_id);
    assert.equal(next.result.deliveries[0].attempts,1);
    assert.equal(contexts.at(-1).error,null,'restored exact context must allow the second tool');
    assert.equal(contexts.at(-1).attached,true);
    await request('POST','/fixture/tool',{step:'completed-second-step'});
    assert.equal(prompts.length,1);assert.equal(acks().length,1);
    assert.deepEqual(await status(anchor),delivered);
    promptRelease.resolve();
    await until(()=>waits===1,'normal admission after prompt return');
    assert.equal(operations('admitted').length,1);
    assert.equal(operations('admitted')[0].result.wake.admitted,true);
    await context(first,'restored');
    history.push({type:'idle',id:'msg_pending_admission_terminal',outcome:'succeeded'});
    nativeRelease.resolve();
    await until(()=>operations('terminal').some(call=>call.status===200),'normal settlement');
    assert.equal(prompts.length,1);assert.equal(acks().length,1);
    assert.deepEqual(await status(anchor),delivered);
    report={scenarioPassed:true,scenario,contexts,delivered};
    return;
   }
   if(scenario==='bootstrap-restored'){
    await cleanup();
    await request('POST','/fixture/bootstrap',{});
    const listed=calls.filter(c=>c.path==='/relay/sessions').length;
    cleanup=await production.setup(ctx);
    await until(()=>calls.filter(c=>c.path==='/relay/sessions').length>listed,'new plugin observed empty startup list');
    assert.equal(operations('enroll').length,1,'startup has no local endpoint/wake');
    const restored=await context(first,'restored');
    assert.equal(restored.result.deliveries[0].attempts,1);
    assert.equal(restored.result.deliveries[0].delivery_id,delivered.delivery_id);
    assert.equal(operations('enroll').length,2,'context owns restoration enrollment');
    assert.notEqual(operations('enroll')[0].body.owner_id,operations('enroll')[1].body.owner_id);
    assert.equal(prompts.length,1);assert.equal(acks().length,1);
    history.push({type:'idle',id:'msg_bootstrap_terminal',outcome:'succeeded'});
    nativeRelease.resolve();await until(()=>waitReturns>0,'original wait released after bootstrap');
    await heartbeat();await until(()=>operations('terminal').some(c=>c.status===200),'restored input terminal');
    const final=await status(anchor);
    assert.equal(final.state,'delivered');assert.equal(final.attempts,1);
    assert.equal(prompts.length,1);assert.equal(acks().length,1);assert.equal(interrupts,0);
    assert.equal(calls.filter(c=>c.path==='/relay/turn').length,0);
    report={scenarioPassed:true,scenario,contexts,delivered,final,
     native:{prompts:prompts.length,waits,waitReturns,interrupts}};
    return;
   }
    if(scenario.startsWith('outage')){
    const toolResult=await request('POST','/fixture/tool',{step:'completed-first-step'});
    toolActions.push(toolResult.step);
     history.push({type:'assistant',id:'msg_before_outage',time:{completed:1},
      content:[{type:'tool',name:'fixture_step',state:{status:'completed'}}]});
     if(recoveryJourney)globalThis.performance={now:()=>outageMono};
    await request('POST','/fixture/outage',{});
    const next=await context(first,'outage'),outcome=contexts.at(-1);
    // This direct unchanged read is a fixture observation, NOT plugin recovery.
     const recoverable=recoveryJourney?null:await request('POST','/relay/opencode/wake',initial.body);
     if(recoverable){
      assert.equal(recoverable.restored,true);assert.equal(recoverable.deliveries.length,1);
      assert.equal(recoverable.deliveries[0].delivery_id,delivered.delivery_id);
      assert.equal(recoverable.deliveries[0].attempts,1);
     }
    const unchanged=await status(anchor);
    for(const key of ['state','attempts','claimed_at','lease_expires_at','expires_at'])
     assert.equal(unchanged[key],delivered[key],key+' unchanged by outage/probe');
     const failures=operations('context').filter(c=>c.status===503||c.status===null);
     assert.equal(failures.length,recoveryJourney?2:1);
     assert.ok(failures.every(c=>c.status===(scenario==='outage-recover-transport'?null:503)));
    assert.equal(calls.filter(c=>c.path==='/fixture/recover').length,1);
    assert.equal(calls.filter(c=>c.path==='/fixture/tool').length,1);
    assert.equal(prompts.length,1);assert.equal(acks().length,1);assert.equal(waitReturns,0);
    assert.equal(operations('terminal').length,0);
    assert.deepEqual(toolActions,['completed-first-step']);
    for(const key of ['owner_id','endpoint_id','scope_generation','generation','delivery_id','native_input_id'])
     assert.equal(next.body[key],initial.body[key],key+' unchanged during outage');
    report={scenarioPassed:false,scenario,firstInput:first.id,contexts,delivered,unchanged,
     recoverable,toolActions,native:{prompts:prompts.length,waits,waitReturns,interrupts}};
    assert.equal(outcome.error,null,'same-input callback must recover after the observed outage');
    assert.equal(outcome.attached,true);assert.equal(next.status,200);
    assert.equal(next.result.restored,true);
      assert.equal(next.result.deliveries[0].delivery_id,delivered.delivery_id);
    assert.equal(next.result.deliveries[0].attempts,delivered.attempts);
      assert.equal(outcome.acks,0);
     if(recoveryJourney){
      assert.equal(outageFailures,2);assert.equal(outageMono-1000,90000);
      const secondTool=await request('POST','/fixture/tool',{step:'completed-second-step'});
      toolActions.push(secondTool.step);
      history.push({type:'assistant',id:'msg_after_outage',time:{completed:2},
       content:[{type:'tool',name:'fixture_second_step',state:{status:'completed'}}]});
     }
    history.push({type:'idle',id:'msg_outage_terminal',outcome:'succeeded'});
    nativeRelease.resolve();await until(()=>waitReturns>0,'original outage input finishes');
    await heartbeat();await until(()=>operations('terminal').some(c=>c.status===200),'outage input terminal');
    const later=await request('POST','/fixture/later',{});
    await heartbeat();await until(()=>prompts.length===2,'later input after outage');
    await context(prompts[1],'initial','FOLLOWUP_界_שלום');
    history.push({type:'idle',id:'msg_later_terminal',outcome:'succeeded'});
    await heartbeat();await until(()=>operations('terminal').filter(c=>c.status===200).length===2,'later terminal');
    const progressed=await status(later),final=await status(anchor);
    assert.equal(final.state,'delivered');assert.equal(final.attempts,1);
    assert.equal(progressed.state,'delivered');assert.equal(progressed.attempts,1);
    assert.equal(acks().length,2);assert.equal(prompts.length,2);assert.equal(interrupts,0);
     assert.deepEqual(toolActions,recoveryJourney?['completed-first-step','completed-second-step']:['completed-first-step']);
     assert.equal(calls.filter(c=>c.path==='/fixture/tool').length,recoveryJourney?2:1);
    assert.equal(calls.filter(c=>c.path==='/relay/turn').length,0);
     report={...report,scenarioPassed:true,final,progressed,controlledOutageMilliseconds:recoveryJourney?90000:0,
     native:{prompts:prompts.length,waits,waitReturns,interrupts}};
    return;
   }
   // More than two same-input model/tool context steps, beyond the original60s claim lease.
  for(let step=1;step<=12;step++){
   await request('POST','/fixture/advance',{seconds:14});
   assert.equal((await heartbeat()).status,200);
   assert.equal(waitReturns,0,'runWake wait must remain held during successful polling');
   if(!unconfirmed&&(step===1||step===12)){
    history.push({type:'assistant',id:'msg_tool_step_'+step,time:{completed:step},
     content:[{type:'tool',name:'fixture_step',state:{status:'completed'}}]});
    const restored=await context(first,'restored');
    assert.equal(restored.result.deliveries[0].attempts,1);
    assert.equal(restored.body.generation,initial.body.generation);
   }
  }
  assert.equal(operations('enroll').length,1,'long native wait alone needs no enrollment repair');
  assert.equal(operations('terminal').length,0);assert.equal(prompts.length,1);
  // Stall ONE poll-owned native check, not runWake.wait; later context ownership reads still work.
  const pollBoundary=operations('poll').length;
  armOwned=true;tick();await ownedEntered.promise;
  await request('POST','/fixture/advance',{seconds:16});
  tick();await pause();assert.equal(operations('poll').length,pollBoundary,'busy poll cannot heartbeat');
  const listed=await request('GET','/relay/sessions?'+new URLSearchParams({...scope,runtime:'opencode'}));
  assert.equal(listed[0].activation.behavior,'passive');
  if(['terminal','rotated'].includes(scenario))
   history.push({type:'idle',id:'msg_control_terminal',outcome:'failed'});
  const contextBoundary=operations('context').length;
  await context(first,scenario==='delivered'?'restored':'refused');
  assert.equal(operations('enroll').length,2,'one recovery enrollment before poll release');
  assert.equal(operations('poll').length,pollBoundary,'recovery must not depend on held poll');
  if(scenario!=='delivered'){
   assert.equal(operations('context').length,contextBoundary+(unconfirmed?2:1));
   const original=operations('context')[0].body;
   const owner=Object.fromEntries(['session_ref','container_ref','endpoint_id','scope_generation',
    'native_location','owner_id'].map(key=>[key,original[key]]));
   const probe=async body=>{
    const response=await fetch(origin+'/relay/opencode/wake',{method:'POST',
     headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    return{status:response.status,result:await response.json()};
   };
   let proof;
   if(scenario==='competing-owner'){
    assert.equal(operations('enroll').at(-1).status,409);
    const replacement=await probe({...owner,owner_id:'opencode-owner-'+'f'.repeat(32),operation:'poll'});
    const denied=await probe({...owner,operation:'poll'});
    assert.equal(replacement.status,200);assert.equal(denied.status,409);
    proof={replacement,denied};
   }else if(['terminal','rotated'].includes(scenario)){
    assert.equal(operations('enroll').at(-1).status,200);
    proof=await probe(original);
    assert.equal(proof.status,scenario==='terminal'?200:409);
    if(scenario==='terminal')assert.deepEqual(proof.result.deliveries,[]);
   }else{
    assert.equal(operations('enroll').at(-1).status,200);
    assert.equal(operations('context').at(-1).status,200);
    assert.deepEqual(operations('context').at(-1).result.deliveries,[]);
   }
   const final=await status(anchor);
   // Status preserves a stored unconfirmed claim; expiry alone does not re-claim it.
   assert.equal(final.state,scenario==='lease'?'claimed':scenario==='ttl'?'expired':'delivered');
   if(scenario==='lease')assert.equal(final.claim_token,delivered.claim_token);
   assert.equal(final.attempts,1);
   for(const key of ['claimed_at','lease_expires_at','expires_at'])assert.equal(final[key],delivered[key],key);
   assert.equal(prompts.length,1);assert.equal(acks().length,1);assert.equal(waitReturns,0);
   report={scenarioPassed:true,scenario,contexts,delivered,final,proof,
    native:{prompts:prompts.length,waits,waitReturns,interrupts}};
   return;
  }
  assert.equal(prompts.length,1);assert.equal(waitReturns,0);
  assert.equal(operations('terminal').length,0);assert.equal(acks().length,1);
  const beforeRecovery=await status(anchor);
  assert.equal(beforeRecovery.state,'delivered');assert.equal(beforeRecovery.attempts,1);
  // Existing poll recovery independently proves the original admitted snapshot can be restored.
  ownedRelease.resolve();
  await until(()=>operations('poll').length>pollBoundary,'held poll resumes after context recovery');
  assert.equal(operations('poll').at(-1).status,200);
  assert.equal(operations('enroll').at(-1).status,200);
  const after=await context(first,'restored');
  for(const key of ['owner_id','endpoint_id','scope_generation','generation','delivery_id','native_input_id'])
   assert.equal(after.body[key],initial.body[key],key+' must not change during recovery');
  assert.equal(acks().length,1);assert.equal(prompts.length,1);
  history.push({type:'idle',id:'msg_first_terminal',outcome:'succeeded'});
  nativeRelease.resolve();await until(()=>waitReturns>0,'original native wait released');
  await heartbeat();await until(()=>operations('terminal').some(c=>c.status===200),'original terminal');
  const later=await request('POST','/fixture/later',{});
  await heartbeat();await until(()=>prompts.length===2,'later native input');
  const second=prompts[1];
  // This input's runWake may finish its already-resolved wait before manual context.
  await context(second,'initial','FOLLOWUP_界_שלום');
  history.push({type:'idle',id:'msg_second_terminal',outcome:'succeeded'});
  await heartbeat();await until(()=>operations('terminal').filter(c=>c.status===200).length===2,'later terminal');
  const unchanged=await status(anchor),progressed=await status(later);
  assert.equal(unchanged.state,'delivered');assert.equal(unchanged.attempts,1);
  assert.equal(progressed.state,'delivered');assert.equal(progressed.attempts,1);
  assert.equal(acks().length,2);assert.equal(prompts.length,2);assert.equal(interrupts,0);
  assert.equal(calls.filter(c=>c.path==='/relay/turn').length,0);
  report={scenarioPassed:true,scenario,controlledBackendSeconds:184,firstInput:first.id,contexts,
   delivered,unchanged,progressed,native:{prompts:prompts.length,waits,waitReturns,interrupts},
   initialSnapshot:snapshot,recoveredSnapshot:operations('enroll').at(-1).result.wake};
 })(),new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(new Error('owned journey exceeded45s')),45000)})]);
}finally{
 globalThis.performance=originalPerformance;
 clearTimeout(watchdog);ownedRelease.resolve();nativeRelease.resolve();await cleanup?.();promptRelease.resolve();
 for(const {child} of children)if(child.exitCode===null&&child.signalCode===null)child.kill();
 await Promise.all(children.map(entry=>entry.closed));
 writeFileSync(process.env.JOURNEY_REPORT,JSON.stringify({report,contexts,logs,http:calls,
   cleanup:{pluginDisposed:disposed.length===(scenario==='bootstrap-restored'?6:3),gitChildrenClosed:children.filter(e=>e.done).length}}));
 assert.ok(children.every(entry=>entry.done));
 assert.deepEqual(disposed.sort(),scenario==='bootstrap-restored'?
  ['compaction','compaction','context','context','prompt','prompt']:['compaction','context','prompt']);
}
""", encoding="utf-8")
    env.update(PALLIUM_PORT=str(server.server_port), PALLIUM_HOOK_ACTOR_REF="fixture-actor",
               JOURNEY_PLUGIN=(root / "integrations/opencode/.opencode/plugins/pallium-v2.mjs").as_uri(),
               JOURNEY_GIT=git, JOURNEY_DIRECTORY=str(workspace),
               JOURNEY_REPORT=str(tmp_path / "journey-report.json"), JOURNEY_ANCHOR=json.dumps(anchor),
               JOURNEY_SCENARIO=scenario)
    try:
        result = subprocess.run([node, str(program)], env=env, cwd=workspace, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=75)
        (tmp_path / "journey-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        (tmp_path / "journey-http.json").write_text(json.dumps(requests), encoding="utf-8")
        (tmp_path / "journey-controls.json").write_text(json.dumps(controls), encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        result = json.loads((tmp_path / "journey-report.json").read_text(encoding="utf-8"))
        assert result["report"]["scenarioPassed"] is True
        if scenario == "lease":
            deadline = datetime.fromisoformat(result["report"]["final"]["lease_expires_at"]).replace(tzinfo=timezone.utc)
            assert deadline <= clock[0]
        if scenario in ("delivered", "outage") or recovery_journey:
            assert len(later) == 1 and result["report"]["progressed"]["delivery_id"] == later[0]["deliveries"][0]["delivery_id"]
        else:
            assert not later
        assert result["cleanup"]["gitChildrenClosed"] > 0
        if recovery_journey:
            assert tool_actions == ["completed-first-step", "completed-second-step"]
            assert len(outage_faults) == 2 and not outage_active.is_set()
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        if startup is not None:
            startup.close()
        assert not thread.is_alive() and server.fileno() == -1


def test_released_native_idle_busy_and_reload(client, tmp_path, test_db_url, monkeypatch):
    _released_native_journey(client, tmp_path, test_db_url, monkeypatch)


def test_released_native_empty_discovery_recovers_without_natural_prompt(client, tmp_path, test_db_url, monkeypatch):
    _released_native_journey(client, tmp_path, test_db_url, monkeypatch, bootstrap=True)


def test_released_native_coalesced_settlement_and_automatic_backlog(client, tmp_path, test_db_url, monkeypatch):
    _released_native_journey(client, tmp_path, test_db_url, monkeypatch, coalesced=True)


def _released_native_journey(client, tmp_path, test_db_url, monkeypatch, *, bootstrap=False, coalesced=False):
    import hashlib

    binary = os.environ.get("PALLIUM_OPENCODE_V2_BINARY")
    if not binary or not Path(binary).is_file():
        pytest.skip("set PALLIUM_OPENCODE_V2_BINARY to the intended released executable (2.3.0 for coalesced qualification)")
    bootstrap_summary = {"host_version_verified": False, "startup_empty_settled": False, "restore_empty_settled": False,
                         "attached_before_ack": False, "provider_payload": False,
                         "exact_native_input": False, "native_settled": False,
                          "public_delivered_once": False, "owned_drain": False}
    coalesced_summary = dict.fromkeys(("host_version_verified", "ordered_coalesced_outcome", "attached_before_ack",
        "lost_terminal_reply_reconciled", "automatic_backlog_over_two", "unique_native_admissions",
        "provider_payloads", "terminal_reload_safe", "missing_proof_compaction_hold", "missing_proof_reload_hold",
        "no_interrupt", "owned_drain", "fresh_supersession_reload_recovery"), False)
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "remote", "add", "origin", "https://example.test/team/relay.git"], check=True)
    locations = [workspace / name for name in ("one", "two", "three")]
    for directory in locations:
        directory.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    subprocess.run(["git", "init", "-q", str(foreign)], check=True)
    subprocess.run(["git", "-C", str(foreign), "remote", "add", "origin", "https://example.test/team/foreign.git"], check=True)
    scope = {"container_ref": "git:example.test/team/relay"}
    requests = []
    primary_requests = []
    session = None
    first_primary = {"instance": None, "value": None}
    primary_lock = threading.Lock()
    release = threading.Event()
    release.set()
    entered = threading.Event()
    tool_emitted = threading.Event()
    service_unavailable = threading.Event()
    relay_client = [client]
    restored_client = []
    fail_context = threading.Event()
    failed_contexts = []
    ingested = []
    capture_reply_lost = threading.Event()
    capture_reply_lost.set()
    lost_captures = []
    assistant_outputs = []
    retirement_armed = threading.Event()
    retirement_blocked = threading.Event()
    retirement_release = threading.Event()
    retirement_resumed = threading.Event()
    retirement_acks = []
    capture_evidence = {}
    wake_responses = []
    terminal_reply_lost = threading.Event()
    if coalesced:
        terminal_reply_lost.set()
    lost_terminals = []
    proof_hold = threading.Event()
    proof_held = threading.Event()
    proof_release = threading.Event()
    terminal_reload_hold = threading.Event()
    terminal_reload_ready = threading.Event()
    terminal_reload_release = threading.Event()

    class RelayHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if coalesced and self.path == "/fixture/wake-wait":
                # Only the plugin's outside-hook wait is gated. Native context,
                # compaction and all settlement evidence still come from the host.
                if proof_hold.is_set():
                    proof_hold.clear()
                    proof_held.set()
                    assert proof_release.wait(30), "after-wait compaction gate not released"
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            if service_unavailable.is_set():
                self.send_error(503, "isolated test outage")
                return
            if self.path == "/relay/opencode/wake" and raw:
                body = json.loads(raw)
                if coalesced and body["operation"] == "poll" and terminal_reload_hold.is_set() and terminal_reload_ready.is_set():
                    assert terminal_reload_release.wait(30), "already-terminal reload gate not released"
                if body["operation"] == "context" and fail_context.is_set():
                    fail_context.clear()
                    failed_contexts.append(body)
                    self.send_error(503, "isolated preclaim failure")
                    return
            if self.path == "/relay/deliveries/ack":
                retirement_acks.append(json.loads(raw))
            response = relay_client[0].request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if coalesced and self.path == "/relay/opencode/wake":
                body = json.loads(raw)
                wake_responses.append({"request": body, "status": response.status_code, "response": response.json()})
                if body["operation"] == "terminal" and response.is_success and terminal_reload_hold.is_set():
                    terminal_reload_ready.set()
                if body["operation"] == "terminal" and response.is_success and terminal_reply_lost.is_set():
                    terminal_reply_lost.clear()
                    lost_terminals.append(body)
                    self.close_connection = True
                    return
            if self.path in ("/items", "/item-and-query") and response.is_success:
                body = json.loads(raw)
                result = response.json()
                ingested.extend(zip(body if isinstance(body, list) else [body], result if isinstance(result, list) else [result]))
                if self.path == "/items" and capture_reply_lost.is_set() and body[0].get("role") == "assistant":
                    capture_reply_lost.clear()
                    lost_captures.append((body[0], result[0]))
                    self.close_connection = True
                    return  # native capture committed; its caller receives no receipt
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            hold = self.path == "/relay/turn" and retirement_armed.is_set() and response.is_success and bool(response.json().get("deliveries"))
            if hold:
                retirement_armed.clear()
                retirement_blocked.set()
                assert retirement_release.wait(30), "retired context response body not released"
            try:
                self.wfile.write(response.content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                if hold:
                    retirement_resumed.set()

        do_GET = do_POST = forward

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if coalesced:
                primary = _primary_gate(self.headers, session, first_primary, entered, primary_lock)
                if primary:
                    primary_requests.append((json.loads(self.headers["x-pallium-fixture"]), body))
            else:
                entered.set()
                primary = True
            if primary:
                assert release.wait(40), "provider not released"
            tool = "IDLE_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False) and not tool_emitted.is_set()
            assistant_marker = f"NATIVE_ASSISTANT_שלום_{len(requests)}"
            if not tool:
                assistant_outputs.append((assistant_marker, body))
            if tool:
                tool_emitted.set()
                # ACK already happened before this model request. Rebuild the
                # complete Pallium app from the same SQLite database before the
                # tool resumes and the next native context hook runs.
                restarted = TestClient(create_app(AppConfig(
                    storage_backend="sqlite", sqlite_url=test_db_url,
                    default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
                    vector_index=VectorIndexConfig(enabled=False))))
                restored_client.append(restarted)
                relay_client[0] = restarted
            compacting = "<template>" in json.dumps(body)
            summary = """## Objective
- Continue the generic fixture.
## Requirements
- (none)
## Decisions
- (none)
## Work State
### Completed
- Initial fixture response.
### Active
- (none)
### Blocked
- (none)
## Next Move
1. Continue the fixture.
## Relevant Files
- (none)
## Important Context
- (none)
"""
            chunks = [
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                     {"index": 0, "id": "call_fixture", "type": "function", "function": {
                         "name": "execute", "arguments": '{"code":"return 1"}'}}
                 ]}, "finish_reason": None}]},
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ] if tool else [
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {
                     "role": "assistant", "content": summary if compacting else assistant_marker}, "finish_reason": None}]},
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            ]
            data = ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    relay = ThreadingHTTPServer(("localhost", 0), RelayHTTP)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    for server in (relay, provider):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("config", "data", "cache", "state", "home", "temp"):
        (tmp_path / name).mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    source = Path(os.environ.get("PALLIUM_OPENCODE_NATIVE_PLUGIN_DIR",
                                root / "integrations" / "opencode" / ".opencode" / "plugins"))
    for name in ("pallium-v2.mjs", "pallium-common.mjs"):
        shutil.copy2(source / name, plugin / name)
    lifecycle = tmp_path / "lifecycle.jsonl"
    wrapper = plugin / "index.js"
    wrapper.write_text("""import production from './pallium-v2.mjs';
import {appendFileSync} from 'node:fs';
import {extractV2AssistantTurn,buildWorkTraceMetadata} from './pallium-common.mjs';
import {randomUUID} from 'node:crypto';
// FIRST_PRIMARY_OBSERVER_START
function primaryBoundary(instance) {
 let live=true,expected=null,slot=null,serial=0,consumed=false,fault=null;
 const input=id=>typeof id==='string'&&id.length<=512&&/^msg_[A-Za-z0-9_-]+$/.test(id);
 const invalidate=reason=>{fault??=reason;if(slot)slot.valid=false;};
 const prompt=args=>{
  if(!live||consumed)return;
  if(expected){invalidate('duplicate first prompt');return;}
  expected=Object.freeze({session:args.sessionID,input:args.id,delivery:args.metadata?.delivery_id,generation:args.metadata?.generation});
  if(typeof expected.session!=='string'||!expected.session||!input(expected.input)||
   typeof expected.delivery!=='string'||!/^relay-delivery-[0-9a-f]{32}$/.test(expected.delivery)||
   !Number.isSafeInteger(expected.generation)||expected.generation<1)invalidate('invalid expected wake');
 };
 const enter=event=>{
  if(!live||consumed)return null;
  if(slot)invalidate('overlapping or superseded context');
  slot={id:++serial,session:event.sessionID,input:event.messages?.findLast(m=>m?.role==='user'&&input(m.id))?.id,
   completed:false,valid:true};
  return slot;
 };
 const complete=(token,resolved)=>{
  if(!token||!live||consumed)return;
  if(slot!==token||!token.valid){invalidate('stale context completion');return;}
  if(token.completed){invalidate('duplicate context completion');return;}
  if(!resolved){invalidate('context threw');return;}
  token.completed=true;
 };
 const observe=event=>{
  if(!live)return;
  const tag={version:1,instance,kind:event.kind,session:event.sessionID};
  if(event.kind==='primary'){
   tag.prefix=!consumed;
   if(!consumed){
    consumed=true; // FIRST primary, not first matching primary. No await before tagging.
    const token=slot;slot=null;
    Object.assign(tag,{invocation:token?.id,input:token?.input,expected,completed:token?.completed===true,
     error:fault||(!expected?'missing expected wake':!token?.valid||!token.completed?'incomplete context':
      token.session!==expected.session||event.sessionID!==expected.session||token.input!==expected.input?'wrong context identity':null)});
    if(token)token.valid=false;
   }
  }
  event.request.headers.set('x-pallium-fixture',JSON.stringify(tag)); // SAME Request; never inspect its body.
 };
 const retire=()=>{live=false;if(slot)slot.valid=false;slot=null;expected=null;};
 const attach=async(ctx,setup,restore)=>{
  let registration,cleanup,closing;
  const close=()=>{
   if(!closing){
    retire(); // Invalidate before any cleanup await or reentrant callback.
    closing=Promise.resolve().then(async()=>{
     const errors=[];
     for(const action of [cleanup,()=>registration?.dispose(),restore]){
      try{await action?.();}catch(error){errors.push(error);}
     }
     if(errors.length)throw new AggregateError(errors,'fixture observer cleanup failed');
    });
   }
   return closing;
  };
  try{registration=await ctx.session.hook('http.request',observe);cleanup=await setup();}
  catch(error){try{await close();}catch(disposal){throw new AggregateError([error,disposal],'fixture setup and disposal failed');}throw error;}
  return close;
 };
 return {prompt,enter,complete,observe,retire,attach};
}
// FIRST_PRIMARY_OBSERVER_END
export default {...production,setup:async ctx=>{
  const instance=randomUUID(),directory=ctx.location.directory;
  const log=(kind,detail={})=>appendFileSync(process.env.PALLIUM_NATIVE_LIFECYCLE,JSON.stringify({kind,time:Date.now(),instance,directory,...detail})+'\\n');
  log('setup');
    const bootstrap=process.env.PALLIUM_NATIVE_BOOTSTRAP==='1',coalesced=process.env.PALLIUM_NATIVE_COALESCED==='1',emptyReads=new Set();
   const primary=coalesced?primaryBoundary(instance):null;
  let activeContext;
  const originalFetch=globalThis.fetch;
  const observedFetch=async(input,init)=>{
   const url=new URL(input?.url??input);
   if(url.port!==process.env.PALLIUM_PORT)return originalFetch(input,init);
    if(url.pathname==='/relay/deliveries/ack'){
     const body=JSON.parse(init.body),text=JSON.stringify(activeContext?.messages||[]);
     log('bootstrap.ack',{attached:text.includes('BOOTSTRAP_PAYLOAD_שלום')&&
      text.includes('Lower-authority context')&&text.includes(body.delivery_id)});
     if(coalesced)log('wake.ack',{deliveryID:body.delivery_id,
      attached:text.includes('Lower-authority context')&&text.includes(body.delivery_id)});
   }
   const response=await originalFetch(input,init);
   if(url.pathname==='/relay/sessions'&&response.ok){
    const read=response.text.bind(response);
    response.text=async()=>{
     const raw=await read();
     if(JSON.stringify(JSON.parse(raw))==='[]'){
      const id=url.searchParams.get('session_ref');
      if(id)emptyReads.add(id);
      else setImmediate(()=>log('bootstrap.startup.empty.settled'));
     }
     return raw;
    };
   }
   return response;
  };
   if(bootstrap||coalesced)globalThis.fetch=observedFetch;
   const session={...ctx.session,context:async args=>{
  const result=await ctx.session.context(args);
  const messages=Array.isArray(result)?result:result.data;
  const turn=extractV2AssistantTurn(messages);
   log('capture.context',{sessionID:args.sessionID,messages,turn,workTrace:turn?buildWorkTraceMetadata(turn):null});
   return result;
   },prompt:async args=>{
     primary?.prompt(args);
     if(coalesced)log('wake.prompt',{sessionID:args.sessionID,inputID:args.id,metadata:args.metadata});
    return ctx.session.prompt(args);
   },wait:async args=>{
    const result=await ctx.session.wait(args);
    if(coalesced)await originalFetch('http://localhost:'+process.env.PALLIUM_PORT+'/fixture/wake-wait');
    return result;
   },interrupt:async args=>{
    if(coalesced)log('wake.interrupt',{sessionID:args.sessionID});
    return ctx.session.interrupt(args);
  },get:async args=>{
   const result=await ctx.session.get(args);
   if(bootstrap&&emptyReads.delete(args.sessionID)&&result?.location?.directory===directory)
    // restore has no await after this post-response owned() check. The next
    // event-loop task runs after that continuation and discovery's finally.
    setImmediate(()=>log('bootstrap.restore.empty.settled',{sessionID:args.sessionID}));
   return result;
  },hook:(name,callback)=>ctx.session.hook(name,async event=>{
  const identity={sessionID:event?.sessionID,inputID:event?.messageID??event?.messages?.findLast(message=>message?.role==='user')?.id};
  log(name+'.enter',identity);
     if((bootstrap||coalesced)&&name==='context')activeContext=event;
    const invocation=name==='context'?primary?.enter(event):null;
    let resolved=false;
    try{const result=await callback(event);resolved=true;return result;}finally{
      primary?.complete(invocation,resolved);
      if((bootstrap||coalesced)&&name==='context')activeContext=undefined;
    log(name+'.done',identity)
   }
 })};
  const restore=()=>{if((bootstrap||coalesced)&&globalThis.fetch===observedFetch)globalThis.fetch=originalFetch;};
  let cleanup;
  try{cleanup=primary?await primary.attach(ctx,()=>production.setup({...ctx,session}),restore):
   await production.setup({...ctx,session});}catch(error){restore();throw error;}
  return async()=>{log('cleanup.enter');try{await cleanup?.();}finally{if(!primary)restore();}
   log('cleanup.done');};
}};
""", encoding="utf-8")
    (plugin / "package.json").write_text('{"type":"module","main":"index.js"}')
    config = {
        "model": "mock/mock-model", "update": "disable", "share": "disabled", "snapshots": False,
        "plugins": [str(plugin)],
        "providers": {"mock": {"package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1", "apiKey": "local-only"},
            "models": {"mock-model": {"limit": {"context": 32000, "output": 2000}}}}},
    }
    (tmp_path / "config" / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not (
        k.startswith(("PALLIUM_", "OPENCODE_")) or k.endswith("API_KEY"))}
    env.update({"PALLIUM_PORT": str(relay.server_port), "PALLIUM_NATIVE_LIFECYCLE": str(lifecycle), "OPENCODE_CONFIG_DIR": str(tmp_path / "config"),
        "OPENCODE_CONFIG_PROJECT_DISABLE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_TEST_HOME": str(tmp_path / "home"),
        "OPENCODE_DB": str(tmp_path / "data" / "native.db"), "OPENCODE_PASSWORD": "local-test",
        "HOME": str(tmp_path / "home"), "USERPROFILE": str(tmp_path / "home"),
        "TEMP": str(tmp_path / "temp"), "TMP": str(tmp_path / "temp"),
        **{"XDG_" + k + "_HOME": str(tmp_path / v) for k, v in (
            ("CONFIG", "config"), ("DATA", "data"), ("CACHE", "cache"), ("STATE", "state"))}})
    if bootstrap:
        env["PALLIUM_NATIVE_BOOTSTRAP"] = "1"
    if coalesced:
        env["PALLIUM_NATIVE_COALESCED"] = "1"
    processes = []
    logs = []

    def start():
        out = queue.Queue()
        process = subprocess.Popen([binary, "serve", "--stdio", "--hostname", "127.0.0.1", "--port", "0"],
            cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(process)

        def read():
            for line in process.stdout:
                logs.append(line)
                out.put(line)

        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            assert process.poll() is None, logs[-15:]
            try:
                line = out.get(timeout=.2)
            except queue.Empty:
                continue
            if line.startswith('{"url":'):
                return process, json.loads(line)["url"]
        pytest.fail("native server did not start: " + str(logs[-15:]))

    def api(method, path, body=None, headers=None):
        if coalesced and method == "GET" and path == "/api/session":
            path += "?limit=2"
        auth = base64.b64encode(b"opencode:local-test").decode()
        request = Request(url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                          headers={"Authorization": "Basic " + auth, "Content-Type": "application/json", **(headers or {})})
        with urlopen(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else None

    def activate_plugin(directory):
        directory = str(directory).replace("\\", "/")
        plugins = api("GET", "/api/plugin?" + urlencode({"location[directory]": directory}))
        assert Path(plugins["location"]["directory"]) == Path(directory), "plugin lookup resolved a different location"
        return plugins if any(row.get("id") == "pallium-v2" and row.get("state", {}).get("status") == "active"
                              and row.get("features", {}).get("server") for row in plugins["data"]) else None

    def eventually(check):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            result = check()
            if result:
                return result
            time.sleep(.1)
        pytest.fail("native lifecycle condition timed out: " + str(logs[-15:]))

    def stop(process, graceful=True):
        if process.poll() is None:
            if graceful:
                process.stdin.close()
            else:
                process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(10)

    def send(payload):
        response = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "opencode:" + session, "payload": payload, **scope})
        assert response.status_code == 200, response.text
        return response.json()

    def delivered(sent):
        status = client.get("/relay/messages/" + sent["message_id"], params=scope)
        assert status.status_code == 200, status.text
        return status.json()["deliveries"][0]["state"] == "delivered"

    try:
        process, url = start()
        if bootstrap or coalesced:
            expected_version = "2.3.0" if coalesced else "2.2.7"
            assert api("GET", "/api/info")["version"] == expected_version, "released host version mismatch"
            bootstrap_summary["host_version_verified"] = True
            coalesced_summary["host_version_verified"] = True
        for directory in ([workspace] if bootstrap or coalesced else [workspace, *locations, foreign]):
            eventually(lambda: activate_plugin(directory))
        def observations():
            return [json.loads(line) for line in lifecycle.read_text(encoding="utf-8").splitlines()]

        if bootstrap:
            eventually(lambda: any(row["kind"] == "bootstrap.startup.empty.settled" for row in observations()))
            bootstrap_summary["startup_empty_settled"] = True
        if coalesced:
            before_sessions = api("GET", "/api/session")
            _assert_session_list(before_sessions, [])
            first_primary["instance"] = [row for row in observations() if row["kind"] == "setup"][-1]["instance"]
        created = api("POST", "/api/session", {"location": {"directory": str(workspace).replace("\\", "/")},
                     **({"title": "Wake lifecycle fixture"} if coalesced else {})})["data"]
        session = created["id"]
        prefix = "/api/session/" + session
        if coalesced:
            assert isinstance(session, str) and re.fullmatch(r"ses_[A-Za-z0-9_-]+", session)
            assert created["title"] == "Wake lifecycle fixture" and not created.get("parentID")
            assert os.path.normcase(os.path.realpath(created["location"]["directory"])) == os.path.normcase(os.path.realpath(workspace))
            confirmed = api("GET", prefix)["data"]
            assert confirmed["id"] == session and confirmed["title"] == created["title"] and not confirmed.get("parentID")
            assert os.path.normcase(os.path.realpath(confirmed["location"]["directory"])) == os.path.normcase(os.path.realpath(workspace))
            sole = api("GET", "/api/session")
            _assert_session_list(sole, [session])
            assert api("GET", prefix + "/context")["data"] == []
            assert api("GET", prefix + "/inbox")["data"] == []
            registered = client.post("/relay/turn", json={"runtime": "opencode", "session_ref": session, **scope})
            assert registered.status_code == 200, registered.text
            assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "sender", **scope}).status_code == 200

            def wake_rows(operation, delivery=None):
                return [row for row in wake_responses if row["status"] == 200
                        and row["request"]["operation"] == operation
                        and (delivery is None or row["request"].get("delivery_id") == delivery)]

            entered.clear()
            release.clear()
            original_payload = "COALESCED_PAYLOAD_שלום" + "界" * 6000 + "_END_OF_FIXTURE"
            original = send(original_payload)
            original_delivery = original["deliveries"][0]["delivery_id"]
            assert entered.wait(15), "automatic wake never reached the blocked provider"
            _assert_first_primary(first_primary, session, original_delivery,
                                  [row for row in observations() if row["kind"] == "wake.prompt"])
            assert delivered(original)
            first_tag, first_body = eventually(lambda: primary_requests and primary_requests[0])
            assert first_tag == first_primary["value"]["tag"]
            claimed, = wake_rows("context", original_delivery)[0]["response"]["deliveries"]
            assert claimed["content_truncated"] is True
            offset = claimed["next_offset"]
            assert 0 < offset < len(original_payload)
            assert claimed["payload"] == original_payload[:offset]
            original_message = original["message_id"]
            primary_text = json.dumps(first_body, ensure_ascii=False)
            assert f"message_id: {original_message}" in primary_text
            assert f"delivery_id: {original_delivery}" in primary_text
            pointer = f'pallium_relay_status(message_id="{original_message}", offset={offset})'
            assert json.dumps(pointer)[1:-1] in primary_text
            assert claimed["payload"] in primary_text and "_END_OF_FIXTURE" not in primary_text
            suffix = client.get(f"/relay/messages/{original_message}", params={
                **scope, "offset": offset, "page_size": 31,
            })
            assert suffix.status_code == 200, suffix.text
            assert suffix.json()["payload_offset"] == offset
            assert suffix.json()["payload"] == original_payload[offset:offset + 31]
            eventually(lambda: wake_rows("admitted", original_delivery))
            admitted = api("POST", prefix + "/prompt", {"id": "msg_coalesced_ordinary",
                "text": "ordinary work שלום 😀", "delivery": "steer"})
            admitted = admitted.get("data", admitted)
            assert admitted["id"] == "msg_coalesced_ordinary"
            release.set()
            api("POST", "/api/experimental/session/" + session + "/wait")
            terminal = eventually(lambda: wake_rows("terminal", original_delivery))[0]["request"]
            context = api("GET", prefix + "/context")["data"]
            start = next(i for i, row in enumerate(context) if row.get("id") == terminal["native_input_id"])
            ordinary = next(i for i, row in enumerate(context) if row.get("id") == "msg_coalesced_ordinary")
            end = next(i for i in range(start + 1, len(context)) if context[i].get("type") == "idle")
            wake_user = context[start]
            assert wake_user["text"] == "[Pallium Relay wake: check the lower-authority Relay context before acting.]"
            assert wake_user["metadata"] == {"pallium_relay_wake": True, "generation": terminal["generation"],
                                              "delivery_id": original_delivery}
            assert start < ordinary < end, "ordinary input was not coalesced before the wake's outcome-idle"
            assert context[end]["id"] == terminal["terminal_message_id"] and context[end]["outcome"] == "succeeded"
            coalesced_summary["ordered_coalesced_outcome"] = True
            assert len(lost_terminals) == 1
            terminal_boundary = next(i for i, row in enumerate(wake_responses)
                                     if row["request"] is terminal) + 1
            eventually(lambda: any(row["request"]["operation"] == "poll" and row["status"] == 200
                                   and row["response"].get("wake") is None for row in wake_responses[terminal_boundary:]))
            coalesced_summary["lost_terminal_reply_reconciled"] = True

            # More than two pending messages, with no further ordinary prompt.
            backlog = [send(f"AUTOMATIC_BACKLOG_{index}_界") for index in range(4)]
            for sent in backlog:
                eventually(lambda sent=sent: delivered(sent))
            api("POST", "/api/experimental/session/" + session + "/wait")
            # Wait for a fresh empty poll, not an earlier pre-backlog observation.
            poll_boundary = len(wake_responses)
            eventually(lambda: any(row["request"]["operation"] == "poll" and row["status"] == 200
                                   and row["response"].get("wake") is None for row in wake_responses[poll_boundary:]))
            prompts = [row for row in observations() if row["kind"] == "wake.prompt"]
            ids = [row["inputID"] for row in prompts]
            assert len(ids) == len(set(ids)) >= 3, "automatic chain must span more than two native wakes"
            assert len(wake_rows("admitted", original_delivery)) == len(wake_rows("terminal", original_delivery)) == 1
            coalesced_summary["automatic_backlog_over_two"] = True
            coalesced_summary["unique_native_admissions"] = True
            for sent in [original, *backlog]:
                delivery_id = sent["deliveries"][0]["delivery_id"]
                acks = [row for row in observations() if row["kind"] == "wake.ack" and row["deliveryID"] == delivery_id]
                assert len(acks) == 1 and acks[0]["attached"] is True
                state = client.get("/relay/messages/" + sent["message_id"], params=scope).json()["deliveries"][0]
                assert state["state"] == "delivered" and state["attempts"] == 1
            assert all(any(marker in json.dumps(body, ensure_ascii=False) for body in requests)
                       for marker in ["COALESCED_PAYLOAD_שלום", *[f"AUTOMATIC_BACKLOG_{i}_界" for i in range(4)]])
            for index, sent in enumerate(backlog):
                marker = f"AUTOMATIC_BACKLOG_{index}_界"
                message_id, delivery_id = sent["message_id"], sent["deliveries"][0]["delivery_id"]
                assert any(
                    all(value in body for value in (marker, f"message_id: {message_id}", f"delivery_id: {delivery_id}"))
                    for body in (json.dumps(data, ensure_ascii=False) for _, data in primary_requests)
                )
            coalesced_summary["attached_before_ack"] = coalesced_summary["provider_payloads"] = True

            def reload_plugin():
                before = observations()
                instance = [row for row in before if row["kind"] == "setup"][-1]["instance"]
                with wrapper.open("a", encoding="utf-8") as stream:
                    stream.write("\n// isolated settlement lifecycle reload\n")
                eventually(lambda: any(row["kind"] == "cleanup.done" and row["instance"] == instance for row in observations()))
                eventually(lambda: any(row["kind"] == "setup" and row["instance"] != instance for row in observations()[len(before):]))

            # Hold retirement polls, not proof: the new owner must read the same
            # already-terminal anchor through normal enrollment after reload.
            terminal_reload_hold.set()
            reload_anchor = send("TERMINAL_RELOAD_ANCHOR_é")
            anchor_delivery = reload_anchor["deliveries"][0]["delivery_id"]
            anchor_terminal = eventually(lambda: wake_rows("terminal", anchor_delivery))[-1]["request"]
            enroll_boundary = len(wake_responses)
            reload_plugin()
            restored = eventually(lambda: [row for row in wake_responses[enroll_boundary:]
                if row["status"] == 200 and row["request"]["operation"] == "enroll"
                and row["request"]["owner_id"] != anchor_terminal["owner_id"]])[-1]["response"]["wake"]
            assert restored["terminal"] is True and restored["native_input_id"] == anchor_terminal["native_input_id"]
            terminal_reload_hold.clear()
            terminal_reload_release.set()
            reloaded = send("AFTER_TERMINAL_RELOAD_é")
            eventually(lambda: delivered(reloaded))
            eventually(lambda: wake_rows("terminal", reloaded["deliveries"][0]["delivery_id"]))
            assert [row["inputID"] for row in observations() if row["kind"] == "wake.prompt"][:len(ids)] == ids
            coalesced_summary["terminal_reload_safe"] = True

            # Hold only the plugin's outside-hook wait continuation while a real
            # native compaction removes its exact input. Never substitute context.
            proof_hold.set()
            missing = send("MISSING_PROOF_PAYLOAD_שלום")
            assert proof_held.wait(15), "outside-hook native wait did not reach the compaction gate"
            missing_delivery = missing["deliveries"][0]["delivery_id"]
            missing_wake = eventually(lambda: wake_rows("admitted", missing_delivery))[-1]["request"]
            assert delivered(missing)
            assert any("MISSING_PROOF_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False) for body in requests)
            api("POST", prefix + "/compact", {"id": "msg_missing_proof_compaction", "delivery": "queue"})
            api("POST", "/api/experimental/session/" + session + "/wait")
            compacted = api("GET", prefix + "/context")["data"]
            assert any(row.get("id") == "msg_missing_proof_compaction" and row.get("status") == "completed" for row in compacted)
            assert not any(row.get("id") == missing_wake["native_input_id"] for row in compacted)
            held_backlog = send("HELD_BACKLOG_界")
            proof_release.set()

            def held_polls_since(boundary):
                polls = [row for row in wake_responses[boundary:] if row["status"] == 200 and row["request"]["operation"] == "poll"]
                return len(polls) >= 2 and all((row["response"].get("wake") or {}).get("native_input_id") == missing_wake["native_input_id"]
                    and row["response"]["wake"]["admitted"] is True and row["response"]["wake"]["terminal"] is False for row in polls)

            boundary = len(wake_responses)
            eventually(lambda: held_polls_since(boundary))
            assert not wake_rows("terminal", missing_delivery) and not delivered(held_backlog)
            coalesced_summary["missing_proof_compaction_hold"] = True
            reload_plugin()
            boundary = len(wake_responses)
            eventually(lambda: held_polls_since(boundary))
            assert not wake_rows("terminal", missing_delivery) and not delivered(held_backlog)
            all_ids = [row["inputID"] for row in observations() if row["kind"] == "wake.prompt"]
            assert len(all_ids) == len(set(all_ids)) and all_ids.count(missing_wake["native_input_id"]) == 1
            assert not any(row["kind"] == "wake.interrupt" for row in observations())
            coalesced_summary["missing_proof_reload_hold"] = coalesced_summary["no_interrupt"] = True

            # Prospective proof only: the restored owner must know this promoted
            # nonterminal G BEFORE a genuinely new ordinary prompt is observed.
            current_owner = [row for row in wake_responses[boundary:] if row["status"] == 200
                             and row["request"]["operation"] == "poll"][-1]["request"]["owner_id"]
            assert current_owner != missing_wake["owner_id"]
            root_acks = len([row for row in observations() if row["kind"] == "wake.ack"
                             and row["deliveryID"] == missing_delivery])
            root_admissions = len(wake_rows("admitted", missing_delivery))
            root_prompts = all_ids.count(missing_wake["native_input_id"])
            root_attempts = client.get("/relay/messages/" + missing["message_id"], params=scope).json()["deliveries"][0]["attempts"]
            assert root_acks == root_admissions == root_prompts == root_attempts == 1
            original_payload = "MISSING_PROOF_PAYLOAD_שלום"
            recovery_context = api("GET", prefix + "/context")["data"]
            assert original_payload not in json.dumps(recovery_context, ensure_ascii=False), "fixture compaction must remove the original payload, not retain it as ordinary history"
            # Original no-replay baseline is BEFORE U, unlike the new automatic
            # suffix boundary below. Recovery itself must not inflate this count.
            root_payload_count = sum(original_payload in json.dumps(body, ensure_ascii=False) for body in requests)

            def assert_no_original_presentation(bodies):
                assert sum(original_payload in json.dumps(body, ensure_ascii=False) for body in bodies) == root_payload_count, "original payload re-presented during recovery or automatic suffix"

            # Negative control changes provider evidence only: no extra ACK,
            # admission, prompt or claim attempt can help detect this replay.
            replay = {"messages": [{"role": "user", "content": original_payload}],
                      "fixture_input_id": "msg_fresh_recovery_ordinary"}
            with pytest.raises(AssertionError, match="original payload re-presented"):
                assert_no_original_presentation([*requests, replay])
            api("POST", prefix + "/prompt", {"id": "msg_fresh_recovery_ordinary",
                "text": "fresh ordinary work 界 😀", "delivery": "queue"})
            api("POST", "/api/experimental/session/" + session + "/wait")
            root_terminal = eventually(lambda: wake_rows("terminal", missing_delivery))[-1]["request"]
            assert_no_original_presentation(requests)
            assert root_terminal["owner_id"] == current_owner
            assert root_terminal["native_input_id"] == missing_wake["native_input_id"]
            assert root_terminal["generation"] == missing_wake["generation"]
            context = api("GET", prefix + "/context")["data"]
            users = [row for row in context if row.get("type") == "user"]
            assert users[-1]["id"] == "msg_fresh_recovery_ordinary"
            u = next(i for i, row in enumerate(context) if row.get("id") == users[-1]["id"])
            t = next(row for row in context[u + 1:] if row.get("type") == "idle")
            assert t["id"] == root_terminal["terminal_message_id"] and t["outcome"] == "succeeded"
            assert not any(row.get("id") == missing_wake["native_input_id"] for row in context)
            eventually(lambda: delivered(held_backlog))  # Manual fallback is NOT suffix evidence.

            # Freeze AFTER root G/T. No earlier latch/backlog/admission may count.
            wake_boundary, observation_boundary, request_boundary = len(wake_responses), len(observations()), len(requests)
            earlier_ids = {row["inputID"] for row in observations() if row["kind"] == "wake.prompt"}
            earlier_generations = {row["request"]["generation"] for row in wake_rows("admitted")}
            ack_boundary = len(retirement_acks)
            suffix_ids, suffix_generations, suffix_terminals = [], [], []
            for index in range(4):
                # Sequential enqueue forces four distinct automatic activations,
                # rather than four payloads batched into one max_messages=3 claim.
                marker = f"FRESH_AUTOMATIC_SUFFIX_{index}_界"
                sent = send(marker)
                delivery_id = sent["deliveries"][0]["delivery_id"]
                eventually(lambda sent=sent: delivered(sent))
                terminal = eventually(lambda: wake_rows("terminal", delivery_id))[-1]["request"]
                api("POST", "/api/experimental/session/" + session + "/wait")
                admitted = wake_rows("admitted", delivery_id)
                assert len(admitted) == len(wake_rows("terminal", delivery_id)) == 1
                assert admitted[0]["request"]["native_input_id"] == terminal["native_input_id"]
                assert terminal["native_input_id"] not in earlier_ids
                assert terminal["generation"] not in earlier_generations
                assert any(row["request"] is terminal for row in wake_responses[wake_boundary:])
                prompts = [row for row in observations()[observation_boundary:] if row["kind"] == "wake.prompt"
                           and row["inputID"] == terminal["native_input_id"]]
                acks = [row for row in observations()[observation_boundary:] if row["kind"] == "wake.ack"
                        and row["deliveryID"] == delivery_id]
                assert len(prompts) == len(acks) == 1 and acks[0]["attached"] is True
                assert len([ack for ack in retirement_acks[ack_boundary:] if ack["delivery_id"] == delivery_id]) == 1
                assert any(marker in json.dumps(body, ensure_ascii=False) for body in requests[request_boundary:])
                native_context = api("GET", prefix + "/context")["data"]
                start = next(i for i, row in enumerate(native_context) if row.get("id") == terminal["native_input_id"])
                end = next(row for row in native_context[start + 1:] if row.get("type") == "idle")
                assert end["id"] == terminal["terminal_message_id"] and end["outcome"] == "succeeded"
                for _ in range(2):
                    state = client.get("/relay/messages/" + sent["message_id"], params=scope).json()["deliveries"][0]
                    assert state["state"] == "delivered" and state["attempts"] == 1
                suffix_ids.append(terminal["native_input_id"])
                suffix_generations.append(terminal["generation"])
                suffix_terminals.append(terminal["terminal_message_id"])
            assert len(set(suffix_ids)) == len(set(suffix_generations)) == len(set(suffix_terminals)) == 4
            assert len([row for row in observations()[observation_boundary:] if row["kind"] == "wake.prompt"]) == 4
            assert len([row for row in observations() if row["kind"] == "wake.ack" and row["deliveryID"] == missing_delivery]) == root_acks
            assert len(wake_rows("admitted", missing_delivery)) == root_admissions
            assert len([row for row in observations() if row["kind"] == "wake.prompt" and row["inputID"] == missing_wake["native_input_id"]]) == root_prompts
            assert client.get("/relay/messages/" + missing["message_id"], params=scope).json()["deliveries"][0]["attempts"] == root_attempts
            assert len(wake_rows("terminal", missing_delivery)) == 1
            assert_no_original_presentation(requests)
            assert not any(row["kind"] == "wake.interrupt" for row in observations())
            coalesced_summary["fresh_supersession_reload_recovery"] = True
            api("DELETE", prefix)
            eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", **scope,
                "include_inactive": True}).json()[0]["state"] == "closed")
            return
        if bootstrap:
            eventually(lambda: any(row["kind"] == "bootstrap.restore.empty.settled" and row.get("sessionID") == session
                                   for row in observations()))
            bootstrap_summary["restore_empty_settled"] = True
            assert client.get("/relay/sessions", params={"runtime": "opencode", **scope}).json() == []
            registered = client.post("/relay/turn", json={"runtime": "opencode", "session_ref": session, **scope})
            assert registered.status_code == 200, registered.text
            assert registered.json()["session"]["session_ref"] == session
            assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "sender", **scope}).status_code == 200
            sent = send("BOOTSTRAP_PAYLOAD_שלום")
            eventually(lambda: delivered(sent))
            eventually(lambda: any("BOOTSTRAP_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False) for body in requests))
            bootstrap_summary["provider_payload"] = True
            api("POST", "/api/experimental/session/" + session + "/wait")
            context = api("GET", prefix + "/context")["data"]
            users = [row for row in context if row.get("type") == "user"]
            assert len(users) == 1 and users[0].get("metadata", {}).get("pallium_relay_wake") is True
            assert users[0]["metadata"]["delivery_id"] == sent["deliveries"][0]["delivery_id"]
            assert users[0]["id"].startswith("msg_pallium_")
            bootstrap_summary["exact_native_input"] = True
            index = next(i for i, row in enumerate(context) if row.get("id") == users[0]["id"])
            assert any(row.get("type") == "idle" and row.get("outcome") == "succeeded" for row in context[index + 1:])
            bootstrap_summary["native_settled"] = True
            acks = [row for row in observations() if row["kind"] == "bootstrap.ack"]
            assert len(acks) == 1 and acks[0]["attached"] is True, "context was not attached before ACK"
            bootstrap_summary["attached_before_ack"] = True
            status = client.get("/relay/messages/" + sent["message_id"], params=scope).json()["deliveries"][0]
            assert status["state"] == "delivered" and status["attempts"] == 1
            bootstrap_summary["public_delivered_once"] = True
            return
        api("POST", prefix + "/prompt", {"id": "msg_natural_first", "text": "NATIVE_USER_שלום", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        eventually(lambda: lost_captures)
        initial_history = api("GET", prefix + "/context")["data"]
        initial_assistant = next(message for message in reversed(initial_history) if message.get("type") == "assistant")
        assert isinstance(initial_assistant["time"]["completed"], (int, float))
        # A normal native compaction hook retries the already-committed capture.
        # It uses the native summary model; no result override or host mutation.
        api("POST", prefix + "/compact", {"id": "msg_capture_compaction", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        compacted_history = api("GET", prefix + "/context")["data"]
        assert any(message.get("id") == "msg_capture_compaction" and message.get("status") == "completed"
                   for message in compacted_history)
        original_capture, original_receipt = lost_captures[0]
        native_retries = [(body, receipt) for body, receipt in ingested
                          if body.get("role") == "assistant" and body["content"] == original_capture["content"]]
        # The compaction callback may overlap the first request's reservation or
        # retry after it clears. Both paths must preserve one underlying source.
        assert 1 <= len(native_retries) <= 2
        assert {receipt["source_item_id"] for _, receipt in native_retries} == {original_receipt["source_item_id"]}
        assert {body["source_id"] for body, _ in native_retries} == {original_capture["source_id"]}
        assert original_capture["source_id"].startswith("oc-assistant-")
        capture_evidence["lost_response_compaction"] = {
            "forwarded_attempts": len(native_retries),
            "observed_path": "stable_id_retry" if len(native_retries) == 2 else "reservation_overlap_or_success_marker",
            "source_id": original_capture["source_id"],
            "source_item_id": original_receipt["source_item_id"],
        }
        listed = eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", "session_ref": session, **scope}).json())
        container = listed[0]["container_ref"]
        scope = {"container_ref": container}
        eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", **scope}).json()[0]["activation"]["integration"] == "opencode_queue")
        assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "sender", **scope}).status_code == 200

        idle = send("IDLE_PAYLOAD_שלום")
        eventually(lambda: delivered(idle))
        eventually(lambda: any("IDLE_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False) for body in requests))
        api("POST", "/api/experimental/session/" + session + "/wait")
        idle_requests = [body for body in requests if "IDLE_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False)]
        assert len(idle_requests) == 2, "Relay context must survive the second native provider/tool step"
        assert restored_client, "Pallium must restart between ACK and continuation"
        multi_history = api("GET", prefix + "/context")["data"]
        last_user = max(i for i, message in enumerate(multi_history) if message.get("type") == "user")
        multi_assistants = [message for message in multi_history[last_user + 1:] if message.get("type") == "assistant"]
        assert len(multi_assistants) == 2
        assert all(isinstance(message.get("time", {}).get("completed"), (int, float)) for message in multi_assistants)
        assert any(part.get("type") == "tool" for message in multi_assistants for part in message.get("content", []))
        multi_ids = [message["id"] for message in multi_assistants]

        def multi_capture():
            observations = [json.loads(line) for line in lifecycle.read_text(encoding="utf-8").splitlines()]
            for observation in reversed(observations):
                if observation["kind"] != "capture.context":
                    continue
                messages = observation["messages"]
                user = max((i for i, message in enumerate(messages) if message.get("type") == "user"), default=-1)
                selected = [message for message in messages[user + 1:] if message.get("type") == "assistant"]
                if selected != multi_assistants:
                    continue
                turn = observation["turn"]
                for body, receipt in ingested:
                    identity = ["opencode-assistant/v1", body.get("agent_ref"), body.get("actor_ref"),
                                body.get("container_ref"), session, multi_ids[-1]]
                    source_id = "oc-assistant-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                    if body.get("role") == "assistant" and body.get("source_id") == source_id:
                        assert body["content"] == turn["assistant_text"]
                        assert body.get("metadata", {}).get("agent_work_trace_turn") == observation["workTrace"]
                        return body, receipt, observation

        multi_body, multi_receipt, multi_observation = eventually(multi_capture)
        expanded = client.get("/source/" + multi_receipt["source_item_id"] + "/context", params={**scope,
            "query_actor_ref": multi_body["actor_ref"], "before": 0, "after": 0})
        assert expanded.status_code == 200, expanded.text
        assert [item["content"] for item in expanded.json()["items"]] == [multi_observation["turn"]["assistant_text"]]
        assert expanded.json()["items"][0]["source_id"] == multi_body["source_id"]
        capture_evidence["multi_step"] = {"public_history": multi_history, "selected_ids": multi_ids,
            "production_turn": multi_observation["turn"], "work_trace": multi_observation["workTrace"],
            "capture": multi_body, "receipt": multi_receipt, "history_readback": expanded.json()}
        for body in idle_requests:
            provider_text = json.dumps(body, ensure_ascii=False)
            assert container in provider_text and session in provider_text and "actor_ref" in provider_text
        # Native source reload invokes production cleanup with the HTTP response
        # body still withheld. A process restart cannot establish this ordering.
        retirement_acks.clear()
        retired = send("RETIRED_BODY_שלום")
        retirement_armed.set()
        api("POST", prefix + "/prompt", {"id": "msg_retirement_pending", "text": "NATIVE_RETIREMENT", "delivery": "queue"})
        assert retirement_blocked.wait(15), "production context never entered the blocked response body"
        before_events = [json.loads(line) for line in lifecycle.read_text(encoding="utf-8").splitlines()]
        held = [event for event in before_events if event["kind"] == "context.enter"
                and event.get("sessionID") == session and event.get("inputID") == "msg_retirement_pending"
                and Path(event["directory"]) == workspace]
        assert len(held) == 1, f"missing or ambiguous held native callback: {held}"
        held_instance = held[0]["instance"]

        def exact_reload():
            events = [json.loads(line) for line in lifecycle.read_text(encoding="utf-8").splitlines()]
            done = [event for event in events if event["kind"] == "cleanup.done" and event["instance"] == held_instance]
            return done and any(event["kind"] == "setup" and Path(event["directory"]) == workspace
                                and event["instance"] != held_instance and event["time"] >= done[0]["time"]
                                for event in events)

        with wrapper.open("a", encoding="utf-8") as stream:
            stream.write("\n// supported native source reload\n")
        eventually(exact_reload)
        lifecycle_events = [json.loads(line) for line in lifecycle.read_text(encoding="utf-8").splitlines()]
        cleanup = [event for event in lifecycle_events if event["kind"] == "cleanup.done" and event["instance"] == held_instance]
        cleanup_enter = [event for event in lifecycle_events if event["kind"] == "cleanup.enter" and event["instance"] == held_instance]
        assert len(cleanup) == len(cleanup_enter) == 1
        assert 0 <= cleanup[0]["time"] - cleanup_enter[0]["time"] < 2000
        assert not retirement_release.is_set()
        assert not retirement_acks
        with lifecycle.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": "body.release", "time": int(time.time() * 1000),
                "instance": held_instance, "directory": str(workspace), "sessionID": session,
                "inputID": "msg_retirement_pending"}) + "\n")
        retirement_release.set()
        assert retirement_resumed.wait(5)
        eventually(lambda: any(event["kind"] == "context.done" and event["instance"] == held_instance
                               and event.get("sessionID") == session and event.get("inputID") == "msg_retirement_pending"
                               for event in (json.loads(line) for line in lifecycle.read_text(encoding="utf-8").splitlines())))
        api("POST", "/api/experimental/session/" + session + "/wait")
        assert not retirement_acks, "retired callback initiated ACK after native cleanup"
        assert all("RETIRED_BODY_שלום" not in json.dumps(body, ensure_ascii=False) for body in requests)
        assert not delivered(retired), "unattached context must remain lease-recoverable"
        # Exercise the real lease expiry/read paths with the same isolated clock
        # seam as the HTTP wake E2E suite, without a minute-long wall-clock wait.
        import storage.sqlite_relay as sqlite_relay
        original_now = sqlite_relay._now
        monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: original_now(value) if value else original_now() + timedelta(seconds=61))
        api("POST", prefix + "/prompt", {"id": "msg_retirement_successor", "text": "NATIVE_RECOVERY", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        eventually(lambda: delivered(retired))
        assert any("RETIRED_BODY_שלום" in json.dumps(body, ensure_ascii=False) for body in requests)
        entered.clear()
        release.clear()
        api("POST", prefix + "/prompt", {"id": "msg_busy_user", "text": "BUSY_USER", "delivery": "queue"})
        assert entered.wait(15)
        busy = send("BUSY_PAYLOAD_é")
        time.sleep(3)
        assert not delivered(busy), "queued wake claimed before model boundary"
        release.set()
        eventually(lambda: delivered(busy))
        api("POST", "/api/experimental/session/" + session + "/wait")
        context = api("GET", prefix + "/context")
        wake_ids = [m["id"] for m in context["data"] if m.get("type") == "user" and m.get("metadata", {}).get("pallium_relay_wake")]
        assert len(wake_ids) == len(set(wake_ids)) == 2
        fail_context.set()
        failure = send("PRECLAIM_RECOVERY_PAYLOAD")
        eventually(lambda: delivered(failure))
        api("POST", "/api/experimental/session/" + session + "/wait")
        assert len(failed_contexts) == 1
        recovered_context = api("GET", prefix + "/context")["data"]
        failed_id = failed_contexts[0]["native_input_id"]
        index = next(i for i, m in enumerate(recovered_context) if m["id"] == failed_id)
        assert recovered_context[index + 1]["type"] == "idle" and recovered_context[index + 1]["outcome"] == "failed"
        assert any(m.get("type") == "user" and m.get("metadata", {}).get("delivery_id") == failed_contexts[0]["delivery_id"]
                   and m["id"] != failed_id for m in recovered_context)
        eventually(lambda: any(body.get("role") == "assistant" for body, _ in ingested))
        for role, marker in (("user", "NATIVE_USER_שלום"), ("assistant", "NATIVE_ASSISTANT_שלום")):
            body, result = next((body, result) for body, result in ingested if body.get("role") == role and marker in body["content"])
            expanded = client.get("/source/" + result["source_item_id"] + "/context", params={**scope,
                "query_actor_ref": body["actor_ref"], "before": 0, "after": 0})
            assert expanded.status_code == 200 and marker in expanded.text
        assistant_sources = [body for body, _ in ingested if body.get("role") == "assistant"]
        natural_marker = assistant_sources[0]["content"]
        automatic_marker = next(marker for marker, model_body in assistant_outputs
            if "IDLE_PAYLOAD_שלום" in json.dumps(model_body, ensure_ascii=False)
            and any(body["content"] == marker for body in assistant_sources))
        assistant_actor = assistant_sources[0]["actor_ref"]
        history_client = relay_client[0]
        history_client.app.state.pallium_service.drain_processing_queue(worker_id="opencode-native-history")
        for marker in (natural_marker, automatic_marker):
            sources = [(body, result) for body, result in ingested
                if body.get("role") == "assistant" and body["content"] == marker]
            assert sources, marker
            identities = {(body["source_id"], result["source_item_id"]) for body, result in sources}
            assert len(identities) == 1, (marker, identities)
            for body, _ in sources:
                assert body["container_ref"] == container and body["thread_ref"] == session and body["actor_ref"] == assistant_actor
            body, result = sources[0]
            history = history_client.post("/query", json={"text": "NATIVE", "container_ref": container,
                "active_session_ref": session, "thread_ref": session, "actor_ref": assistant_actor,
                "visibility": "private", "trigger_origin": "agent_pull", "limit": 50, "source_only": True})
            assert history.status_code == 200, history.text
            assert result["source_item_id"] in json.dumps(history.json())
            expanded = history_client.get("/source/" + result["source_item_id"] + "/context", params={**scope,
                "query_actor_ref": assistant_actor, "before": 0, "after": 0})
            assert expanded.status_code == 200 and marker in expanded.text
        foreign_history = history_client.post("/query", json={"text": "NATIVE", "container_ref": "git:example.test/team/foreign",
            "active_session_ref": session, "thread_ref": session, "visibility": "private",
            "trigger_origin": "agent_pull", "limit": 50, "source_only": True})
        assert foreign_history.status_code == 200, foreign_history.text
        foreign_rows = [json.dumps(row, ensure_ascii=False) for row in foreign_history.json()["results"]]
        for marker in (natural_marker, automatic_marker):
            assert not any(marker in row for row in foreign_rows), marker
        assert all(not body["content"].startswith("[Pallium Relay wake:") for body, _ in ingested)
        stop(process, graceful=False)
        reload_message = send("RELOAD_PAYLOAD")
        service_unavailable.set()
        process, url = start()
        eventually(lambda: activate_plugin(workspace))
        time.sleep(3)
        service_unavailable.clear()
        eventually(lambda: delivered(reload_message))
        eventually(lambda: any("RELOAD_PAYLOAD" in json.dumps(body) for body in requests))
        api("DELETE", prefix)
        eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", **scope, "include_inactive": True}).json()[0]["state"] == "closed")
    finally:
        release.set()
        proof_release.set()
        terminal_reload_release.set()
        retirement_release.set()
        (tmp_path / "native.log").write_text("".join(logs), encoding="utf-8")
        (tmp_path / "capture-evidence.json").write_text(json.dumps(capture_evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        for process in processes:
            stop(process)
        for server in (relay, provider):
            server.shutdown()
            server.server_close()
        for restarted in restored_client:
            restarted.close()
        if bootstrap:
            bootstrap_summary["owned_drain"] = all(process.poll() is not None for process in processes)
            summary = os.environ.get("PALLIUM_OPENCODE_BOOTSTRAP_SUMMARY")
            if summary:
                Path(summary).write_text(json.dumps(bootstrap_summary), encoding="utf-8")
            assert bootstrap_summary["owned_drain"], "owned native host did not drain"
        if coalesced:
            coalesced_summary["owned_drain"] = all(process.poll() is not None for process in processes)
            (tmp_path / "settlement-evidence.json").write_text(json.dumps(wake_responses, ensure_ascii=False, indent=2), encoding="utf-8")
            summary = os.environ.get("PALLIUM_OPENCODE_COALESCED_SUMMARY")
            if summary:
                Path(summary).write_text(json.dumps(coalesced_summary), encoding="utf-8")
            assert coalesced_summary["owned_drain"], "owned native host did not drain"


def test_capture_callbacks_retry_through_real_http_and_history(client, tmp_path):
    """Production hook + HTTP writes: count persisted receipts, including lost replies."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the production OpenCode caller")
    attempts, ingested = {}, []
    gates = {(marker, attempt): (threading.Event(), threading.Event())
             for marker, count in (("CONCURRENT_שלום", 1), ("DISPOSE_שלום", 2),
                                   ("DELETE_שלום", 2), ("REBIND_שלום", 2))
             for attempt in range(1, count + 1)}
    generation = [0]

    class CaptureHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            payload = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.startswith("/fixture/"):
                control = json.loads(raw)
                if self.path == "/fixture/rebind":
                    generation[0] += 1
                    return self.reply(200, True)
                held, release = gates[(control["marker"], control["attempt"])]
                if self.path == "/fixture/held":
                    return self.reply(200, held.is_set())
                release.set()
                return self.reply(200, True)
            body = json.loads(raw) if self.path == "/items" else None
            marker = body[0]["content"] if body else None
            if marker:
                attempts[marker] = attempts.get(marker, 0) + 1
                attempt = attempts[marker]
                if marker == "REJECT_שלום" and attempt == 1:
                    return self.reply(503, {"detail": "isolated precommit rejection"})
            response = client.request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            result = response.json()
            # Exercise the existing rebind envelope while source writes/readback
            # still cross production HTTP. This is not native host qualification.
            if self.path in ("/relay/turn", "/relay/opencode/wake") and result.get("session"):
                result["session"]["scope_generation"] = generation[0]
            if body and response.is_success:
                ingested.extend(zip(body, result))
                if (marker, attempt) in gates:
                    held, release = gates[(marker, attempt)]
                    held.set()
                    assert release.wait(15), "capture reply was not released"
                if marker == "LOST_שלום" and attempt == 1:
                    self.close_connection = True  # committed source, no receipt delivered
                    return
                if marker == "MALFORMED_שלום" and attempt == 1:
                    return self.reply(200, {})
            try:
                self.reply(response.status_code, result)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # retired caller; the source is already committed

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("localhost", 0), CaptureHTTP)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = Path(__file__).resolve().parents[1]
    plugin_dir = Path(os.environ.get("PALLIUM_OPENCODE_NATIVE_PLUGIN_DIR",
                                    root / "integrations/opencode/.opencode/plugins"))
    program = tmp_path / "capture-caller.mjs"
    program.write_text("""import assert from 'node:assert/strict';
const {default:production}=await import(process.env.CAPTURE_PLUGIN);
const {pinContainer,removeSessionPin}=await import(new URL('./pallium-common.mjs',process.env.CAPTURE_PLUGIN));
const cwd=process.env.CAPTURE_DIRECTORY;
let sessionID='ses_capture_http',history=[],hooks={},cleanup,eventReady,events=[];
const ctx={location:{directory:cwd},app:{log(){}},session:{
 hook:async(name,callback)=>{hooks[name]=callback;return{dispose:async()=>{}}},
 get:async()=>({location:{directory:cwd}}),context:async()=>({data:history}),
},event:{subscribe:async function*({signal}){
 while(!signal.aborted){
  if(events.length){const [event,done]=events.shift();yield event;done();continue}
  await new Promise(resolve=>{eventReady=resolve;signal.addEventListener('abort',resolve,{once:true})});
 }
}}};
const capture=()=>hooks.compaction({sessionID});
const assistant=(id,text)=>({type:'assistant',id,time:{created:0,completed:1},content:[{type:'text',text}]});
const rows=(name,id='msg_'+name,text=name+'_שלום')=>history=[
 {type:'user',id:'msg_user_'+name,text:'generic fixture'},
 assistant(id,text),
];
const control=async(path,marker='CONCURRENT_שלום',attempt=1)=>(await fetch(
 'http://localhost:'+process.env.PALLIUM_PORT+'/fixture/'+path,
 {method:'POST',body:JSON.stringify({marker,attempt})})).json();
const waitHeld=async(marker='CONCURRENT_שלום',attempt=1)=>{
 const until=Date.now()+5000;while(!await control('held',marker,attempt)){
  assert.ok(Date.now()<until,'capture request did not reach the HTTP barrier');
  await new Promise(resolve=>setTimeout(resolve,5));
 }
};
const context=async(id)=>hooks.context({sessionID,messages:[
 {id,role:'user',content:[{type:'text',text:'generic rebind fixture'}]},
]});
try{
 cleanup=await production.setup(ctx);
 rows('CONCURRENT');const first=capture();
 await waitHeld();
 await capture();await control('release');await first;await capture();
 rows('REJECT');await capture();await capture();await capture();
 rows('MALFORMED');await capture();await capture();await capture();
 rows('LOST');await capture();await cleanup();cleanup=await production.setup(ctx);
 await capture();await capture();
 rows('SAME_TEXT','msg_same_a');await capture();
 rows('SAME_TEXT','msg_same_b');await capture();
 rows('SCOPE');await capture();await cleanup();cleanup=await production.setup(ctx);await capture();
 process.env.PALLIUM_HOOK_ACTOR_REF='other-actor';await capture();
 process.env.PALLIUM_HOOK_ACTOR_REF='fixture-actor';
 pinContainer(sessionID,'path:other:123',undefined,'fixture-actor');await capture();
 removeSessionPin(sessionID);sessionID='ses_capture_sibling';await capture();
 sessionID='ses_capture_http';
 rows('EMPTY',undefined,'');await capture();
 rows('EMPTY',undefined,'   ');await capture();
 const tool={type:'tool',name:'read',state:{status:'completed',input:{filePath:'/tmp/fixture-שלום.txt'},
  content:[{type:'text',text:'read result'}]}};
 rows('TOOL_ONLY');history[1].content=[tool];await capture();
 rows('MAX',undefined,'😀'.repeat(10000));await capture();await capture();
 rows('OVERMAX',undefined,'😀'.repeat(10000)+'x');await capture();
 rows('ELIGIBLE');delete history[1].time.completed;await capture();
 history[1].time.completed=0;await capture();await capture();
 rows('MULTISTEP');history.unshift(assistant('invalid','previous turn'));
 history[2].content=[tool];history.push(assistant('msg_middle','first'),
  assistant('msg_next','middle'),assistant('msg_final','last 😀'));
 await capture();await capture();
 for(const mode of ['DISPOSE','DELETE','REBIND']){
  rows(mode);
  if(mode==='REBIND')await context('msg_bind_initial');
  const retired=capture();await waitHeld(mode+'_שלום',1);
  if(mode==='DISPOSE'){await cleanup();cleanup=await production.setup(ctx)}
  else if(mode==='DELETE')await new Promise(resolve=>{
   events.push([{type:'session.deleted',data:{sessionID}},resolve]);eventReady?.();
  });
  else{await control('rebind');await context('msg_bind_successor')}
  const successor=capture();await waitHeld(mode+'_שלום',2);
  await control('release',mode+'_שלום',1);await retired;await capture();
  await control('release',mode+'_שלום',2);await successor;await capture();
 }
}finally{
 for(const [marker,count] of [['CONCURRENT_שלום',1],['DISPOSE_שלום',2],['DELETE_שלום',2],['REBIND_שלום',2]])
  for(let attempt=1;attempt<=count;attempt++)await control('release',marker,attempt);
 await cleanup?.();removeSessionPin(sessionID);removeSessionPin('ses_capture_sibling');
}
""", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not (
        key.startswith(("PALLIUM_", "OPENCODE_")) or key.endswith("API_KEY"))}
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "TEMP", "TMP"):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    env.update({"PALLIUM_PORT": str(server.server_port), "PALLIUM_HOOK_ACTOR_REF": "fixture-actor",
                "CAPTURE_PLUGIN": (plugin_dir / "pallium-v2.mjs").as_uri(),
                "CAPTURE_DIRECTORY": str(tmp_path)})
    try:
        result = subprocess.run([node, str(program)], env=env, cwd=tmp_path,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        (tmp_path / "capture-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        counts = {"CONCURRENT_שלום": 1, "REJECT_שלום": 2, "MALFORMED_שלום": 2,
                  "LOST_שלום": 2, "SAME_TEXT_שלום": 2, "SCOPE_שלום": 5, "😀" * 10000: 1,
                  "ELIGIBLE_שלום": 1, "first\nmiddle\nlast 😀": 1,
                  "DISPOSE_שלום": 2, "DELETE_שלום": 2, "REBIND_שלום": 2}
        assert attempts == counts  # no empty/tool-only/over-max/unfinished write
        assert len(ingested) == sum(counts.values()) - 1  # precommit rejection
        for text in counts:
            receipts = [(body, reply) for body, reply in ingested if body["content"] == text]
            unique = {reply["source_item_id"] for _, reply in receipts}
            assert len(unique) == (2 if text == "SAME_TEXT_שלום" else 4 if text == "SCOPE_שלום" else 1)
            for receipt in unique:
                body = next(body for body, reply in receipts if reply["source_item_id"] == receipt)
                expanded = client.get("/source/" + receipt + "/context", params={
                    "container_ref": body["container_ref"], "query_actor_ref": body["actor_ref"],
                    "before": 0, "after": 0})
                assert expanded.status_code == 200
                item, = expanded.json()["items"]
                assert item["content"] == text
                assert item["source_id"] == body["source_id"]
                assert item["actor_ref"] == body["actor_ref"]
                assert item["thread_ref"] == body["thread_ref"]
                for wrong in ({"container_ref": "path:unrelated:456"}, {"query_actor_ref": "unrelated-actor"}):
                    denied = client.get("/source/" + receipt + "/context", params={
                        "container_ref": body["container_ref"], "query_actor_ref": body["actor_ref"], **wrong})
                    assert denied.status_code == 404
                if text == "first\nmiddle\nlast 😀":
                    # History's public response omits raw metadata; assert the
                    # recognized trace at the actual production HTTP boundary.
                    assert body["metadata"]["agent_work_trace_turn"]["files_read"] == ["/tmp/fixture-שלום.txt"]
    finally:
        for _, release in gates.values():
            release.set()
        server.shutdown()
        server.server_close()
