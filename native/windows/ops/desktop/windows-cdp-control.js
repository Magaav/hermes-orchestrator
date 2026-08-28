"use strict";

const { execFile } = require("node:child_process");
const http = require("node:http");

const INSPECT_OPERATION = "inspect_windows_cdp_persistent";
const STATUS_OPERATION = "status_windows_cdp_persistent";
const ACT_OPERATION = "act_windows_cdp_persistent";
const PROCEDURE_OPERATION = "execute_windows_cdp_procedure";
const INSPECT_SCHEMA = "hermes.wasm_agent.windows_cdp_inspection.v1";
const STATUS_SCHEMA = "hermes.wasm_agent.windows_cdp_status.v1";
const ACT_SCHEMA = "hermes.wasm_agent.windows_cdp_action.v1";
const PROCEDURE_SCHEMA = "hermes.wasm_agent.windows_cdp_procedure.v1";

const SEMANTIC_DOM_HELPERS = `
    const interactiveRoles=new Set(['button','checkbox','combobox','gridcell','link','listitem','menuitem','menuitemcheckbox','menuitemradio','option','radio','row','searchbox','slider','spinbutton','switch','tab','textbox','treeitem']);
    const visible=(n)=>n&&n.nodeType===1&&n.getClientRects().length&&!n.disabled&&n.getAttribute('aria-disabled')!=='true';
    const label=(n)=>String(n?.getAttribute?.('aria-label')||n?.innerText||n?.value||n?.getAttribute?.('title')||'').trim().replace(/\\s+/g,' ');
    const structuralAction=(n)=>visible(n)&&(/^(a|button|input|textarea|select|option)$/i.test(n.tagName)||n.isContentEditable||n.hasAttribute('tabindex')||interactiveRoles.has(String(n.getAttribute('role')||'').toLowerCase()));
    const pointerCache=new WeakMap();
    const points=(n)=>{if(!visible(n))return false;if(pointerCache.has(n))return pointerCache.get(n);const value=getComputedStyle(n).cursor==='pointer';pointerCache.set(n,value);return value;};
    const compactEventTarget=(n)=>{if(!visible(n))return false;const r=n.getBoundingClientRect();const name=label(n);return name.length>0&&name.length<=500&&r.width*r.height<=innerWidth*innerHeight*0.6&&(typeof n.onclick==='function'||n.hasAttribute('onclick')||(points(n)&&!points(n.parentElement)));};
    const namedTarget=(n)=>visible(n)&&(n.hasAttribute('aria-label')||n.hasAttribute('title'))&&label(n).length<=500;
    const semanticNodes=(limit)=>{const result=[];for(const n of document.querySelectorAll('body *')){if(structuralAction(n)||namedTarget(n)||compactEventTarget(n)){result.push(n);if(result.length>=limit)break;}}return result;};
    const semanticRole=(n)=>{const explicit=String(n?.getAttribute?.('role')||'').toLowerCase();if(explicit)return explicit;if(n?.isContentEditable||/^(textarea)$/i.test(n?.tagName||''))return 'textbox';if(/^input$/i.test(n?.tagName||''))return String(n.type||'').toLowerCase()==='search'?'searchbox':'textbox';return String(n?.tagName||'').toLowerCase();};
    const semanticRegion=(n)=>{const owner=n?.closest?.('header,nav,aside,main,footer,form,[role=search],[role=main],[role=navigation],[role=dialog]');return String(owner?.getAttribute?.('role')||owner?.tagName||'body').toLowerCase();};
    const viewportZone=(n)=>{const r=n.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;return (x<innerWidth/3?'left':x>innerWidth*2/3?'right':'center')+'-'+(y<innerHeight/3?'top':y>innerHeight*2/3?'bottom':'middle');};
    const targetFingerprint=(n)=>{if(!visible(n))return null;const r=n.getBoundingClientRect();return {role:semanticRole(n),editable:('value'in n)||n.isContentEditable,region:semanticRegion(n),zone:viewportZone(n),bounds:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]};};
`;

function clean(value, limit = 500) { return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit); }
function normalizeUrl(value) { try { const url = new URL(String(value || "")); return ["http:", "https:"].includes(url.protocol) ? url.href : ""; } catch { return ""; } }
function portScript() { return [
  "$ErrorActionPreference = 'Stop';",
  "$profile = Join-Path $env:APPDATA 'WASM-Agent\\browser\\cdp-persistent';",
  "$activePort = Join-Path $profile 'DevToolsActivePort'; if (-not (Test-Path -LiteralPath $activePort)) { throw 'persistent_cdp_active_port_not_found' };",
  "$lines = @(Get-Content -LiteralPath $activePort -ErrorAction Stop); $port = [int]$lines[0];",
  "[ordered]@{ port=$port } | ConvertTo-Json -Compress;",
].join("\n"); }

function discover(timeoutMs = 5000) {
  return new Promise((resolve) => execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", portScript()], { timeout: timeoutMs, maxBuffer: 8192, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => resolve({ ok: !error, stdout: String(stdout || ""), error: clean(stderr || error?.message) })));
}

function requestJson(port, path, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const request = http.get({ host: "127.0.0.1", port, path, timeout: timeoutMs }, (response) => {
      let body = ""; response.setEncoding("utf8"); response.on("data", (chunk) => { if (body.length < 128 * 1024) body += chunk; });
      response.on("end", () => { try { resolve(JSON.parse(body)); } catch { resolve([]); } });
    });
    request.on("timeout", () => request.destroy(new Error("cdp_request_timeout")));
    request.on("error", () => resolve([]));
  });
}

async function withPageSession(port, targetUrl, handler, timeoutMs = 10000) {
  const targets = await requestJson(port, "/json/list");
  const pages = Array.isArray(targets) ? targets.filter((item) => item?.type === "page" && item?.webSocketDebuggerUrl) : [];
  const page = (targetUrl && pages.find((item) => normalizeUrl(item.url).startsWith(targetUrl))) || pages.find((item) => /^https?:/.test(String(item.url || ""))) || pages[0];
  if (!page) throw new Error("windows_cdp_page_missing");
  const Socket = globalThis.WebSocket;
  if (typeof Socket !== "function") throw new Error("windows_cdp_websocket_unavailable");
  return new Promise((resolve, reject) => {
    const socket = new Socket(page.webSocketDebuggerUrl); let nextId = 0; let finished = false;
    const pending = new Map();
    const finish = (error, value) => { if (finished) return; finished = true; clearTimeout(timer); try { socket.close(); } catch {} error ? reject(error) : resolve(value); };
    const timer = setTimeout(() => finish(new Error("windows_cdp_session_timeout")), timeoutMs);
    const send = (method, params = {}) => new Promise((resolveCommand, rejectCommand) => {
      const id = ++nextId; pending.set(id, { resolve: resolveCommand, reject: rejectCommand });
      socket.send(JSON.stringify({ id, method, params }));
    });
    socket.addEventListener("open", async () => { try { finish(null, await handler(send, page)); } catch (error) { finish(error); } });
    socket.addEventListener("message", (event) => {
      let message; try { message = JSON.parse(String(event.data)); } catch { return; }
      const waiter = pending.get(message.id); if (!waiter) return; pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message || "windows_cdp_command_failed")); else waiter.resolve(message);
    });
    socket.addEventListener("error", () => finish(new Error("windows_cdp_socket_failed")));
  });
}

function runtimeValue(message) {
  if (message?.result?.exceptionDetails) throw new Error("windows_cdp_evaluate_failed");
  return message?.result?.result?.value;
}

async function evaluate(port, targetUrl, expression, timeoutMs = 10000) {
  return withPageSession(port, targetUrl, async (send, page) => ({
    targetId: clean(page.id, 160),
    value: runtimeValue(await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })),
  }), timeoutMs);
}

function inspectExpression(maxElements, queryText = "", querySelector = "") {
  return `(() => {
    ${SEMANTIC_DOM_HELPERS}
    const esc = (value) => CSS.escape(String(value));
    const path = (node) => { const parts=[]; for(let n=node;n&&n.nodeType===1&&n!==document.documentElement;n=n.parentElement){ if(n.id){parts.unshift('#'+esc(n.id));break;} const siblings=[...n.parentElement.children].filter(x=>x.tagName===n.tagName); parts.unshift(n.tagName.toLowerCase()+(siblings.length>1?':nth-of-type('+(siblings.indexOf(n)+1)+')':'')); } return parts.join('>'); };
    const actionPath=(node,fallback)=>{const text=label(node).trim();return text&&!('value'in node)&&!node.isContentEditable?'text='+text.slice(0,300):path(fallback||node);};
    const nodes=semanticNodes(${maxElements});
    const controls=nodes.map((n,i)=>({ref:'c'+(i+1),locator:path(n),role:semanticRole(n),name:label(n).slice(0,180),value:n.isContentEditable?String(n.innerText||'').slice(0,300):('value' in n)?String(n.value||'').slice(0,300):undefined,selected:n.getAttribute('aria-selected')==='true'||n.selected===true,focused:document.activeElement===n,editable:('value' in n)||n.isContentEditable,target:targetFingerprint(n)}));
    const editable_targets=[...document.querySelectorAll('[contenteditable=true],textarea,input')].filter(visible).slice(0,16).map((n,i)=>{const scope=n.closest('main,[role=main],form,footer,[role=dialog]')||n.parentElement;return {ref:'e'+(i+1),locator:path(n),scopeLocator:path(scope),role:semanticRole(n),name:label(n).slice(0,180),value:n.isContentEditable?String(n.innerText||'').slice(0,300):String(n.value||'').slice(0,300),focused:document.activeElement===n,target:targetFingerprint(n)};});
    const inViewport=(n)=>{const r=n.getBoundingClientRect();return r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth;};
    const describe=(n,i,prefix)=>{const r=n.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,hit=inViewport(n)?document.elementFromPoint(x,y):null;const ancestry=[];let actionNode=(structuralAction(n)||compactEventTarget(n))?n:null;for(let p=n;p&&p!==document.body&&ancestry.length<6;p=p.parentElement){const pr=p.getBoundingClientRect();if(!actionNode&&(structuralAction(p)||compactEventTarget(p)||points(p)))actionNode=p;ancestry.push({locator:path(p),tag:p.tagName.toLowerCase(),role:p.getAttribute('role')||'',name:label(p).slice(0,180),tabindex:p.getAttribute('tabindex'),onclick:typeof p.onclick==='function'||p.hasAttribute('onclick'),cursor:getComputedStyle(p).cursor,rect:[Math.round(pr.x),Math.round(pr.y),Math.round(pr.width),Math.round(pr.height)]});}return {ref:prefix+(i+1),locator:path(n),actionLocator:actionPath(n,actionNode||n),role:semanticRole(n),name:label(n).slice(0,300),value:n.isContentEditable?String(n.innerText||'').slice(0,300):('value'in n)?String(n.value||'').slice(0,300):undefined,editable:('value'in n)||n.isContentEditable,target:targetFingerprint(n),viewport:inViewport(n),rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],hit:hit?{locator:path(hit),role:semanticRole(hit),name:label(hit).slice(0,180)}:null,ancestry};};
    const query=${JSON.stringify(String(queryText || "").trim().slice(0, 300))};
    const matches=query?[...document.querySelectorAll('body *')].filter(n=>visible(n)&&!('value'in n)&&!n.isContentEditable&&label(n)===query).sort((a,b)=>Number(inViewport(b))-Number(inViewport(a))).slice(0,12).map((n,i)=>describe(n,i,'t')):[];
    const selector=${JSON.stringify(String(querySelector || "").trim().slice(0, 300))};let selectorNodes=[];if(selector){try{selectorNodes=[...document.querySelectorAll(selector)].filter(visible).slice(0,12);}catch{selectorNodes=[];}}const selector_matches=selectorNodes.map((n,i)=>describe(n,i,'s'));
    const text=String(document.body?.innerText||'').trim().replace(/\\n{3,}/g,'\\n\\n').slice(0,12000);
    return {ok:true,url:location.href,title:document.title.slice(0,240),controls,editable_targets,matches,selector_matches,text,page_text:text};
  })()`;
}

function targetPrelude(locator) {
  return `${SEMANTIC_DOM_HELPERS}
    const locator=${JSON.stringify(String(locator || ""))};
    const resolve=(raw)=>{if(raw.startsWith('text=')){const wanted=raw.slice(5).replace(/^['"]|['"]$/g,'').trim();const matches=[...document.querySelectorAll('body *')].filter(n=>visible(n)&&!('value'in n)&&!n.isContentEditable&&label(n)===wanted);matches.sort((a,b)=>{const named=(n)=>Number(n.hasAttribute('aria-label')||n.hasAttribute('title'));return named(b)-named(a)||a.children.length-b.children.length||label(a).length-label(b).length;});return matches[0]||null;}try{return document.querySelector(raw);}catch{return null;}};
    const node=resolve(locator);`;
}

function targetPointExpression(locator) {
  return `(()=>{${targetPrelude(locator)}if(!node)return {ok:false,code:'browser_ref_missing'};node.scrollIntoView({block:'center',inline:'center'});const r=node.getBoundingClientRect();if(!(r.width>0&&r.height>0))return {ok:false,code:'browser_target_not_actionable'};const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);if(!hit||!(hit===node||node.contains(hit)||hit.contains(node)))return {ok:false,code:'browser_target_obscured'};node.focus?.({preventScroll:true});return {ok:true,x,y,name:label(node).slice(0,300),value:('value'in node)?String(node.value||'').slice(0,1000):'',focused:document.activeElement===node};})()`;
}

function setValueExpression(locator, value) {
  return `(()=>{${targetPrelude(locator)}if(!node)return {ok:false,code:'browser_ref_missing'};node.focus();const value=${JSON.stringify(String(value || ""))};if(node.isContentEditable){document.execCommand('selectAll',false,null);document.execCommand('insertText',false,value);}else if('value'in node){const setter=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node),'value')?.set;setter?setter.call(node,value):(node.value=value);node.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:value}));node.dispatchEvent(new Event('change',{bubbles:true}));}else return {ok:false,code:'browser_target_not_editable'};return {ok:true,name:label(node).slice(0,300),value:('value'in node)?String(node.value||'').slice(0,1000):'',focused:document.activeElement===node};})()`;
}

function observeTargetExpression(locator, focus = false) {
  return `(()=>{${targetPrelude(locator)}if(!node)return {ok:false,code:'browser_ref_missing'};${focus ? "node.focus();" : ""}return {ok:true,name:label(node).slice(0,300),value:('value'in node)?String(node.value||'').slice(0,1000):'',focused:document.activeElement===node};})()`;
}

function targetContractExpression(locator, expected = {}) {
  return `(()=>{${targetPrelude(locator)}const expected=${JSON.stringify(expected || {})};if(!node)return {ok:false,code:'browser_ref_missing'};let scope=null;try{scope=document.querySelector(String(expected.scope_locator||''));}catch{}const actual=targetFingerprint(node),name=label(node).slice(0,300),mismatch=[];for(const key of ['role','region','editable']){if(Object.prototype.hasOwnProperty.call(expected,key)&&actual?.[key]!==expected[key])mismatch.push(key);}if(!scope||!(scope===node||scope.contains(node)))mismatch.push('scope');if(expected.name_contains&&!name.includes(String(expected.name_contains)))mismatch.push('name');return {ok:mismatch.length===0,code:mismatch.length?'browser_target_contract_mismatch':null,expected,actual,mismatch,name,value:node.isContentEditable?String(node.innerText||'').slice(0,1000):('value'in node)?String(node.value||'').slice(0,1000):''};})()`;
}

function proofStateExpression(locator) {
  return `(()=>{${targetPrelude(locator)}return {url:location.href,page_text:String(document.body?.innerText||'').slice(0,16000),name:node?label(node).slice(0,300):'',value:(node&&'value'in node)?String(node.value||'').slice(0,1000):'',focused:document.activeElement===node};})()`;
}

function settleExpression() {
  return `(async()=>new Promise(resolveDone=>{let quiet=setTimeout(done,250),hard=setTimeout(done,1500);const observer=new MutationObserver(()=>{clearTimeout(quiet);quiet=setTimeout(done,200);});function done(){clearTimeout(quiet);clearTimeout(hard);observer.disconnect();resolveDone({ok:true});}observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,characterData:true});}))()`;
}

function recoveryLens(step = {}) {
  const locator = String(step.locator || "");
  const queryText = locator.startsWith("text=") ? locator.slice(5).replace(/^["']|["']$/g, "").trim().slice(0, 300) : "";
  const querySelector = ["set_value", "key"].includes(String(step.action || "")) ? "[contenteditable=true],textarea,input" : "";
  return { queryText, querySelector };
}

function failureEvidence(step, stepIndex, failed, recovery = {}) {
  const lens = recoveryLens(step);
  return {
    ok: false,
    code: failed?.code || "browser_ref_missing",
    failedStepIndex: stepIndex,
    failedAction: clean(step?.action, 40),
    failedLocator: clean(step?.locator, 2048),
    recovery: {
      queryText: lens.queryText,
      querySelector: lens.querySelector,
      matches: Array.isArray(recovery.matches) ? recovery.matches.slice(0, 12) : [],
      selectorMatches: Array.isArray(recovery.selector_matches) ? recovery.selector_matches.slice(0, 12) : [],
    },
  };
}

function postcondition(expect, observed) {
  if (expect?.property === "value") return observed.value === String(expect.equals);
  if (expect?.property === "focused") return observed.focused === expect.equals;
  if (expect?.property === "url") return observed.url === String(expect.equals);
  if (expect?.property === "page_text_contains") return String(observed.page_text || "").includes(String(expect.equals));
  if (expect?.property === "name") return observed.name === String(expect.equals);
  return false;
}

function textOccurrences(text, expected) {
  const value = String(expected ?? ""); if (!value) return 0;
  let count = 0; for (let index = 0; (index = String(text || "").indexOf(value, index)) !== -1; index += value.length) count += 1;
  return count;
}

function postconditionEvidence(expect, before, observed) {
  const beforeMatched = postcondition(expect, before); const afterMatched = postcondition(expect, observed);
  const evidence = { property:String(expect?.property || ""), beforeMatched, afterMatched, transitioned:afterMatched && !beforeMatched };
  if (expect?.property === "page_text_contains") {
    evidence.beforeCount = textOccurrences(before.page_text, expect.equals);
    evidence.afterCount = textOccurrences(observed.page_text, expect.equals);
    evidence.transitioned = afterMatched && evidence.afterCount > evidence.beforeCount;
  }
  return evidence;
}

function keyParameters(key, type) {
  const names = { Enter: ["Enter", 13], Escape: ["Escape", 27], Tab: ["Tab", 9], Backspace: ["Backspace", 8], ArrowUp: ["ArrowUp", 38], ArrowDown: ["ArrowDown", 40], ArrowLeft: ["ArrowLeft", 37], ArrowRight: ["ArrowRight", 39] };
  const [code, virtualKey] = names[key] || [key.length === 1 ? `Key${key.toUpperCase()}` : key, key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0];
  return { type, key, code, windowsVirtualKeyCode: virtualKey, nativeVirtualKeyCode: virtualKey, ...(type === "keyDown" && key.length === 1 ? { text: key, unmodifiedText: key } : {}) };
}

function assertionStateExpression(assertions) {
  const encoded = JSON.stringify(assertions);
  return `(()=>{const assertions=${encoded};const clean=v=>String(v??'').replace(/\\s+/g,' ').trim().slice(0,4096);const select=(raw,scopeRaw)=>{raw=String(raw||'');let scope=null;try{scope=document.querySelector(String(scopeRaw||''));}catch{}if(!scope)return[];if(raw.startsWith('text=')){const wanted=raw.slice(5).replace(/^['"]|['"]$/g,'').trim();return [...scope.querySelectorAll('*')].filter(n=>clean(n.innerText||n.textContent||'')===wanted);}try{return [...scope.querySelectorAll(raw)];}catch{return[];}};return assertions.map(a=>{const nodes=select(a.selector,a.scope_locator);let value=null;if(a.property==='count')value=nodes.length;else if(a.property==='text')value=clean(nodes.map(n=>n.innerText||n.textContent||'').join(' '));else if(a.property==='last_text')value=clean(nodes.length?(nodes[nodes.length-1].innerText||nodes[nodes.length-1].textContent||''):'');else if(a.property==='value'){const n=nodes[0];value=n?(n.isContentEditable?clean(n.innerText):String(n.value??'')):'';}else if(a.property==='focused')value=nodes.some(n=>n===document.activeElement||n.contains(document.activeElement));return{id:String(a.id||'').slice(0,80),selector:String(a.selector||'').slice(0,2048),property:String(a.property||''),value};});})()`;
}

function completionProof(assertions, before, after) {
  const prior = new Map((Array.isArray(before) ? before : []).map((item) => [item.id, item]));
  const current = new Map((Array.isArray(after) ? after : []).map((item) => [item.id, item]));
  const records = assertions.map((assertion) => {
    const beforeValue = prior.get(assertion.id)?.value;
    const afterValue = current.get(assertion.id)?.value;
    let passed = false;
    if (assertion.transition === "count_increased") passed = Number(afterValue) > Number(beforeValue);
    else if (assertion.transition === "became_equal") passed = afterValue === assertion.equals && beforeValue !== assertion.equals;
    else if (assertion.transition === "equals_after") passed = afterValue === assertion.equals;
    return { id:assertion.id, property:assertion.property, transition:assertion.transition, expected:assertion.equals, before:beforeValue, after:afterValue, passed };
  });
  return { ok: records.length > 0 && records.every((item) => item.passed), assertions: records };
}

async function interact(port, targetUrl, args, timeoutMs = 10000, session = withPageSession) {
  const steps = Array.isArray(args.steps) ? args.steps : [{ locator:args.locator, action:args.action, value:args.value, key:args.key }];
  const assertions = Array.isArray(args.assertions) ? args.assertions : [];
  return session(port, targetUrl, async (send, page) => {
    if (args.page_target_id && clean(args.page_target_id,160) !== clean(page.id,160)) return {targetId:clean(page.id,160),value:{ok:false,code:"browser_page_target_mismatch"}};
    const runtime = async (expression) => runtimeValue(await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }));
    const before = await runtime(proofStateExpression(steps[steps.length - 1].locator));
    const assertionBefore = assertions.length ? await runtime(assertionStateExpression(assertions)) : [];
    let lastTarget = { ok:false, name:"", value:"", focused:false };
    const actionSteps = [];
    for (const [stepIndex, step] of steps.entries()) {
      let targetProof = null;
      if (["set_value", "key"].includes(String(step.action || "")) && step.target_contract) {
        targetProof = await runtime(targetContractExpression(step.locator, step.target_contract));
        if (!targetProof?.ok) { const lens=recoveryLens(step); const recovery=await runtime(inspectExpression(40,lens.queryText,lens.querySelector)); return {targetId:clean(page.id,160),value:failureEvidence(step,stepIndex,targetProof,recovery)}; }
      }
      if (step.action === "click") {
        lastTarget = await runtime(targetPointExpression(step.locator));
        if (!lastTarget?.ok) { const lens=recoveryLens(step); const recovery=await runtime(inspectExpression(40,lens.queryText,lens.querySelector)); return {targetId:clean(page.id,160),value:failureEvidence(step,stepIndex,lastTarget,recovery)}; }
        await send("Input.dispatchMouseEvent", { type:"mouseMoved", x:lastTarget.x, y:lastTarget.y, button:"none" });
        await send("Input.dispatchMouseEvent", { type:"mousePressed", x:lastTarget.x, y:lastTarget.y, button:"left", buttons:1, clickCount:1 });
        await send("Input.dispatchMouseEvent", { type:"mouseReleased", x:lastTarget.x, y:lastTarget.y, button:"left", buttons:0, clickCount:1 });
      } else if (step.action === "set_value") {
        lastTarget = await runtime(setValueExpression(step.locator, step.value));
        if (!lastTarget?.ok) { const lens=recoveryLens(step); const recovery=await runtime(inspectExpression(40,lens.queryText,lens.querySelector)); return {targetId:clean(page.id,160),value:failureEvidence(step,stepIndex,lastTarget,recovery)}; }
      } else if (step.action === "key") {
        lastTarget = await runtime(observeTargetExpression(step.locator, true));
        if (!lastTarget?.ok) { const lens=recoveryLens(step); const recovery=await runtime(inspectExpression(40,lens.queryText,lens.querySelector)); return {targetId:clean(page.id,160),value:failureEvidence(step,stepIndex,lastTarget,recovery)}; }
        const key = String(step.key || "");
        await send("Input.dispatchKeyEvent", keyParameters(key, "rawKeyDown"));
        await send("Input.dispatchKeyEvent", keyParameters(key, "keyUp"));
      }
      actionSteps.push({ index:stepIndex, action:String(step.action||""), locator:clean(step.locator,2048), dispatched:true, target:clean(lastTarget?.name,300), ...(targetProof?{targetProof:{expected:targetProof.expected,actual:targetProof.actual}}:{}) });
      await runtime(settleExpression());
    }
    const snapshot = await runtime(inspectExpression(120));
    const refreshedTarget = await runtime(observeTargetExpression(steps[steps.length - 1].locator));
    const target = refreshedTarget?.ok ? refreshedTarget : lastTarget;
    const observed = { name:String(target?.name||"").slice(0,300), value:String(target?.value||"").slice(0,1000), focused:target?.focused===true, url:String(snapshot?.url||""), page_text:String(snapshot?.page_text||snapshot?.text||"").slice(0,16000), controls:Array.isArray(snapshot?.controls)?snapshot.controls:[] };
    const changed = ["name", "value", "focused", "url", "page_text"].filter((field) => before[field] !== observed[field]);
    if (assertions.length) {
      const assertionAfter = await runtime(assertionStateExpression(assertions));
      const proof = completionProof(assertions, assertionBefore, assertionAfter);
      const dispatched = actionSteps.length === steps.length && actionSteps.every((item)=>item.dispatched);
      return { targetId:clean(page.id,160), value:{ok:proof.ok,action:{dispatched,steps:actionSteps},observation:{url:observed.url,target:observed.name,assertions:assertionAfter},completion_proof:proof,code:proof.ok?null:(dispatched?"commit_unknown":"browser_procedure_proof_failed")} };
    }
    const evidence = postconditionEvidence(args.expect || {}, before, observed); const verified = evidence.transitioned && changed.length > 0;
    const code = !evidence.afterMatched ? "browser_postcondition_mismatch" : evidence.transitioned ? "browser_action_no_observed_change" : "browser_postcondition_preexisting";
    return { targetId:clean(page.id,160), value:{ok:verified,observed,changed,postcondition:evidence,postconditionVerified:verified,code} };
  }, timeoutMs);
}

function actExpression(args) {
  const steps = Array.isArray(args.steps) ? args.steps : [{ locator:args.locator, action:args.action, value:args.value, key:args.key }];
  const encodedSteps = JSON.stringify(steps); const expect = JSON.stringify(args.expect || {});
  return `(async()=>{ const steps=${encodedSteps};let node=null;${SEMANTIC_DOM_HELPERS}const resolve=(raw)=>{const locator=String(raw||'');if(locator.startsWith('text=')){const wanted=locator.slice(5).replace(/^['"]|['"]$/g,'').trim();const matches=[...document.querySelectorAll('body *')].filter(n=>visible(n)&&!('value'in n)&&!n.isContentEditable&&label(n)===wanted);matches.sort((a,b)=>a.children.length-b.children.length||label(a).length-label(b).length);return matches[0]||null;}try{return document.querySelector(locator);}catch{return null;}};const settle=()=>new Promise(resolveDone=>{let quiet=setTimeout(done,250),hard=setTimeout(done,1500);const observer=new MutationObserver(()=>{clearTimeout(quiet);quiet=setTimeout(done,200);});function done(){clearTimeout(quiet);clearTimeout(hard);observer.disconnect();resolveDone();}observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,characterData:true});});
    const esc=(value)=>CSS.escape(String(value));const path=(item)=>{const parts=[];for(let n=item;n&&n.nodeType===1&&n!==document.documentElement;n=n.parentElement){if(n.id){parts.unshift('#'+esc(n.id));break;}const siblings=[...n.parentElement.children].filter(x=>x.tagName===n.tagName);parts.unshift(n.tagName.toLowerCase()+(siblings.length>1?':nth-of-type('+(siblings.indexOf(n)+1)+')':''));}return parts.join('>');};const actionPath=(item)=>{const text=label(item).trim();return text&&!('value'in item)&&!item.isContentEditable?'text='+text.slice(0,300):path(item);};
    const beforeNode=resolve(steps[steps.length-1].locator);const before={url:location.href,page_text:String(document.body?.innerText||'').slice(0,16000),name:beforeNode?label(beforeNode).slice(0,300):'',value:(beforeNode&&'value'in beforeNode)?String(beforeNode.value||'').slice(0,1000):'',focused:document.activeElement===beforeNode};
    for(const [stepIndex,step] of steps.entries()){node=resolve(step.locator);const action=String(step.action||''),value=String(step.value||''),key=String(step.key||'');if(!node){const queryText=String(step.locator||'').startsWith('text=')?String(step.locator||'').slice(5).replace(/^["']|["']$/g,'').trim().slice(0,300):'',querySelector=['set_value','key'].includes(action)?'[contenteditable=true],textarea,input':'',describe=(n,i,prefix)=>({ref:prefix+(i+1),locator:path(n),actionLocator:actionPath(n),role:n.getAttribute('role')||n.tagName.toLowerCase(),name:label(n).slice(0,300),value:('value'in n)?String(n.value||'').slice(0,300):undefined,editable:('value'in n)||n.isContentEditable}),matches=queryText?[...document.querySelectorAll('body *')].filter(n=>visible(n)&&!('value'in n)&&!n.isContentEditable&&label(n)===queryText).slice(0,12).map((n,i)=>describe(n,i,'t')):[];let selectorNodes=[];if(querySelector){try{selectorNodes=[...document.querySelectorAll(querySelector)].filter(visible).slice(0,12);}catch{selectorNodes=[];}}return {ok:false,code:'browser_ref_missing',failedStepIndex:stepIndex,failedAction:action.slice(0,40),failedLocator:String(step.locator||'').slice(0,2048),recovery:{queryText,querySelector,matches,selectorMatches:selectorNodes.map((n,i)=>describe(n,i,'s'))}};}
      if(action==='click'){node.focus?.();node.click();}else if(action==='set_value'){node.focus();if(node.isContentEditable){document.execCommand('selectAll',false,null);document.execCommand('insertText',false,value);}else{const setter=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node),'value')?.set;setter?setter.call(node,value):(node.value=value);node.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:value}));node.dispatchEvent(new Event('change',{bubbles:true}));}}else if(action==='key'){node.focus();node.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true}));node.dispatchEvent(new KeyboardEvent('keypress',{key,bubbles:true}));node.dispatchEvent(new KeyboardEvent('keyup',{key,bubbles:true}));}else return {ok:false,code:'browser_action_unsupported'};await settle();}
    const controls=semanticNodes(120).map((n,i)=>({ref:'c'+(i+1),locator:path(n),role:n.getAttribute('role')||n.tagName.toLowerCase(),name:label(n).slice(0,180),value:('value'in n)?String(n.value||'').slice(0,300):undefined,selected:n.getAttribute('aria-selected')==='true'||n.selected===true,focused:document.activeElement===n,editable:('value'in n)||n.isContentEditable}));
    node=resolve(steps[steps.length-1].locator);const observed={name:node?label(node).slice(0,300):'',value:(node&&'value'in node)?String(node.value||'').slice(0,1000):'',focused:document.activeElement===node,url:location.href,page_text:String(document.body?.innerText||'').slice(0,16000),controls};const changed=['name','value','focused','url','page_text'].filter(field=>before[field]!==observed[field]);const e=${expect};const matches=(state)=>e.property==='value'?state.value===String(e.equals):e.property==='focused'?state.focused===e.equals:e.property==='url'?state.url===String(e.equals):e.property==='page_text_contains'?String(state.page_text||'').includes(String(e.equals)):e.property==='name'?state.name===String(e.equals):false;const occurrences=(text,value)=>{value=String(value??'');if(!value)return 0;let count=0;for(let index=0;(index=String(text||'').indexOf(value,index))!==-1;index+=value.length)count++;return count;};const beforeMatched=matches(before),afterMatched=matches(observed),beforeCount=e.property==='page_text_contains'?occurrences(before.page_text,e.equals):undefined,afterCount=e.property==='page_text_contains'?occurrences(observed.page_text,e.equals):undefined,transitioned=e.property==='page_text_contains'?afterMatched&&afterCount>beforeCount:afterMatched&&!beforeMatched,postcondition={property:String(e.property||''),beforeMatched,afterMatched,transitioned,...(beforeCount===undefined?{}:{beforeCount,afterCount})};const verified=transitioned&&changed.length>0,code=!afterMatched?'browser_postcondition_mismatch':transitioned?'browser_action_no_observed_change':'browser_postcondition_preexisting';return {ok:verified,observed,changed,postcondition,postconditionVerified:verified,code};})()`;
}

async function run(context = {}, dependencies = {}) {
  const operation = context.operation?.name || ""; const args = context.args || {};
  if ((dependencies.platform || process.platform) !== "win32") return { ok: false, operation, failureClassification: "windows_native_shell_required" };
  const found = await (dependencies.discover || discover)();
  if (operation === STATUS_OPERATION && !found.ok) return {schema:STATUS_SCHEMA,operation,ok:true,realm:"browser_cdp_persistent",state:"closed",process:false,debugEndpoint:false,pageCount:0,pages:[],recoverable:true,cause:"windows_cdp_persistent_unavailable",next:"client.windows.browser.cdp.default.open",proof:["windows.browser.cdp.lifecycle.observed"]};
  if (!found.ok) return { ok:false, operation, failureClassification:"windows_cdp_persistent_unavailable", error:found.error };
  let port; try { port = Number(JSON.parse(found.stdout).port); } catch { return {ok:false,operation,failureClassification:"windows_cdp_discovery_invalid"}; }
  if (operation === STATUS_OPERATION) {
    const targets = await (dependencies.requestJson || requestJson)(port, "/json/list");
    const pages = (Array.isArray(targets) ? targets : []).filter((item) => item?.type === "page").slice(0, 16).map((item) => ({id:clean(item.id,160),url:normalizeUrl(item.url),title:clean(item.title,240)}));
    return {schema:STATUS_SCHEMA,operation,ok:true,realm:"browser_cdp_persistent",state:pages.length?"open_page":"open_no_page",process:true,debugEndpoint:true,port,pageCount:pages.length,pages,recoverable:pages.length===0,cause:pages.length?null:"windows_cdp_page_missing",next:pages.length?null:"client.windows.browser.cdp.default.open",proof:["windows.browser.cdp.lifecycle.observed"]};
  }
  const targetUrl = normalizeUrl(args.target_url || ""); const call = dependencies.evaluate || evaluate;
  if (operation === INSPECT_OPERATION) {
    const evaluated = await call(port, targetUrl, inspectExpression(Math.max(1, Math.min(Number(args.max_elements)||120, 200)), args.query_text, args.query_selector));
    const value = evaluated.value || {}; return { schema:INSPECT_SCHEMA,operation,ok:value.ok===true,realm:"browser_cdp_persistent",targetId:evaluated.targetId,url:normalizeUrl(value.url),title:clean(value.title,240),controls:Array.isArray(value.controls)?value.controls.slice(0,200):[],editableTargets:Array.isArray(value.editable_targets)?value.editable_targets.slice(0,16):[],matches:Array.isArray(value.matches)?value.matches.slice(0,12):[],selectorMatches:Array.isArray(value.selector_matches)?value.selector_matches.slice(0,12):[],text:clean(value.text,12000),proof:["windows.browser.cdp.dom.snapshot"] };
  }
  if (operation === ACT_OPERATION || operation === PROCEDURE_OPERATION) {
    const steps = Array.isArray(args.steps) ? args.steps : [{locator:args.locator,action:args.action,value:args.value,key:args.key}];
    const assertions = Array.isArray(args.assertions) ? args.assertions : [];
    const procedureInvalid = operation === PROCEDURE_OPERATION && (!String(args.page_target_id||"") || !assertions.length || assertions.length > 6 || assertions.some((item) => !String(item?.id||"") || !String(item?.selector||"") || !String(item?.scope_locator||"") || !["count","text","last_text","value","focused"].includes(String(item?.property||"")) || !["count_increased","became_equal","equals_after"].includes(String(item?.transition||""))) || steps.some((step) => ["set_value","key"].includes(String(step?.action||"")) && (!step?.target_contract || !String(step.target_contract.role||"") || !String(step.target_contract.scope_locator||"") || !String(step.target_contract.name_contains||"") || step.target_contract.editable !== true)));
    if (!steps.length || steps.length > (operation === PROCEDURE_OPERATION ? 6 : 4) || steps.some((step) => !String(step?.locator||"") || !["click","set_value","key"].includes(String(step?.action||"")) || (step.action === "key" && !String(step.key||""))) || (operation === ACT_OPERATION && !args.expect) || procedureInvalid) return {schema:operation===PROCEDURE_OPERATION?PROCEDURE_SCHEMA:ACT_SCHEMA,operation,ok:false,failureClassification:operation===PROCEDURE_OPERATION?"windows_cdp_procedure_invalid":"windows_cdp_action_invalid"};
    const actionCall = dependencies.interact || (dependencies.evaluate ? ((activePort, activeUrl, activeArgs) => dependencies.evaluate(activePort, activeUrl, actExpression(activeArgs))) : interact);
    const evaluated = await actionCall(port, targetUrl, args); const value=evaluated.value||{};
    if (operation === PROCEDURE_OPERATION) return {schema:PROCEDURE_SCHEMA,operation,ok:value.ok===true,realm:"browser_cdp_persistent",targetId:evaluated.targetId,action:value.action||{},observation:value.observation||{},completion_proof:value.completion_proof||{},proof:value.ok===true?["windows.browser.cdp.procedure.completed"]:[],failureClassification:value.ok===true?null:(value.code||"windows_cdp_procedure_unverified")};
    return {schema:ACT_SCHEMA,operation,ok:value.ok===true,realm:"browser_cdp_persistent",targetId:evaluated.targetId,action:steps.length > 1 ? "transaction" : String(steps[0].action),stepCount:steps.length,observed:value.observed||{},changed:Array.isArray(value.changed)?value.changed:[],postcondition:value.postcondition||{},postconditionVerified:value.postconditionVerified===true,...(Number.isInteger(value.failedStepIndex)?{failedStepIndex:value.failedStepIndex,failedAction:clean(value.failedAction,40),failedLocator:clean(value.failedLocator,2048),recovery:value.recovery||{}}:{}),proof:value.postconditionVerified===true?["windows.browser.cdp.action.observed"]:[],failureClassification:value.ok===true?null:(value.code||"windows_cdp_postcondition_unverified")};
  }
  return {ok:false,operation,failureClassification:"windows_cdp_operation_invalid"};
}

module.exports = { STATUS_OPERATION, INSPECT_OPERATION, ACT_OPERATION, PROCEDURE_OPERATION, STATUS_SCHEMA, INSPECT_SCHEMA, ACT_SCHEMA, PROCEDURE_SCHEMA, normalizeUrl, inspectExpression, actExpression, assertionStateExpression, completionProof, targetPointExpression, targetContractExpression, recoveryLens, failureEvidence, interact, run };
