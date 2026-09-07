"""End-to-end coverage for integration-owned stable actor identities."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn


def test_opencode_public_relay_lifecycle_uses_configured_actor_against_real_service(
    client, tmp_path: Path,
) -> None:
    """The public hooks register, deliver/ack, reuse their pin, and close."""
    repos = []
    for name, git_name in (("source", "Source Git Name"), ("target", "Target Git Name")):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", git_name],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        repos.append(repo)
    source, target = repos

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            client.app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started

    plugin = Path("integrations/opencode/.opencode/plugins/pallium.mjs").resolve().as_uri()
    common = Path("integrations/opencode/.opencode/plugins/pallium-common.mjs").resolve().as_uri()
    script = r'''import pluginFactory from "__PLUGIN__";
import * as P from "__COMMON__";
const client = {app:{log(){}},session:{messages:async()=>({data:[]})}};
const sourceDir = __SOURCE__, targetDir = __TARGET__;
const sourceHooks = await pluginFactory({client, directory:sourceDir});
const targetHooks = await pluginFactory({client, directory:targetDir});
const actor = P.deriveActorRef(sourceDir);
const sourceContainer = P.deriveContainerRef(sourceDir);
const targetContainer = P.deriveContainerRef(targetDir);
const sourceMessage = {sessionID:"oc-source", role:"user"};
const targetMessage = {sessionID:"oc-target", role:"user"};
await sourceHooks["chat.message"]({}, {message:sourceMessage, parts:[{type:"text",text:"hi"}]});
await targetHooks["chat.message"]({}, {message:targetMessage, parts:[{type:"text",text:"hi"}]});
await targetHooks["experimental.chat.messages.transform"]({}, {messages:[{info:targetMessage, parts:[{type:"text",text:"hi"}]}]});
const sessions = await (await fetch(`${P.PALLIUM_BASE_URL}/relay/sessions?container_ref=${encodeURIComponent(targetContainer)}&actor_ref=${encodeURIComponent(actor)}`)).json();
const targetEndpoint = sessions.find((session) => session.session_ref === "oc-target").endpoint_id;
const sent = await (await fetch(`${P.PALLIUM_BASE_URL}/relay/messages`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sender_runtime:"opencode",sender_session_ref:"oc-source",recipient:targetEndpoint,payload:"real service delivery",container_ref:sourceContainer,actor_ref:actor})})).json();
await targetHooks["chat.message"]({}, {message:targetMessage, parts:[{type:"text",text:"deliver this"}]});
const transformed = {messages:[{info:targetMessage, parts:[{type:"text",text:"deliver this"}]}]};
await targetHooks["experimental.chat.messages.transform"]({}, transformed);
process.env.PALLIUM_HOOK_ACTOR_REF = "changed actor";
await targetHooks["chat.message"]({}, {message:targetMessage, parts:[{type:"text",text:"reuse pin"}]});
const cachedActor = P.resolveActorRef(targetDir, "oc-target");
const status = await (await fetch(`${P.PALLIUM_BASE_URL}/relay/messages/${sent.message_id}?container_ref=${encodeURIComponent(targetContainer)}&actor_ref=${encodeURIComponent(actor)}`)).json();
await targetHooks.event({event:{type:"session.deleted",properties:{sessionID:"oc-target"}}});
const inactive = await (await fetch(`${P.PALLIUM_BASE_URL}/relay/sessions?container_ref=${encodeURIComponent(targetContainer)}&actor_ref=${encodeURIComponent(actor)}&include_inactive=true`)).json();
process.stdout.write(JSON.stringify({actor,sessions,status,cachedActor,text:transformed.messages[0].parts[0].text,inactive}), () => process.exit(0));
'''.replace("__PLUGIN__", plugin).replace("__COMMON__", common).replace(
        "__SOURCE__", json.dumps(source.as_posix())
    ).replace("__TARGET__", json.dumps(target.as_posix()))
    environment = {
        **os.environ,
        "PALLIUM_PORT": str(port),
        "PALLIUM_HOOK_ACTOR_REF": "  מפעיל 統一  ",
        "USERPROFILE": str(tmp_path / "node-home"),
        "HOME": str(tmp_path / "node-home"),
    }
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            env=environment,
            timeout=20,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    observed = json.loads(result.stdout)
    assert observed["actor"] == observed["cachedActor"] == "מפעיל 統一"
    assert [(row["runtime"], row["session_ref"]) for row in observed["sessions"]] == [
        ("opencode", "oc-target")
    ]
    assert "real service delivery" in observed["text"]
    assert observed["status"]["deliveries"][0]["state"] == "delivered"
    assert next(
        row for row in observed["inactive"] if row["session_ref"] == "oc-target"
    )["state"] == "closed"
