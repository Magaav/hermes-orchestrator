"use strict";

const crypto = require("node:crypto");

const OPERATION = "inspect_windows_cdp_runtime";
const SCHEMA = "hermes.wasm_agent.windows_cdp_runtime_inspection.v1";

function loadControl() {
  const resolved = require.resolve("./windows-cdp-control");
  delete require.cache[resolved];
  return require(resolved);
}

function clean(value, limit = 500) { return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, limit); }
function boundedInt(value, fallback, maximum) {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? Math.max(1, Math.min(parsed, maximum)) : fallback;
}

function runtimeInspectExpression(args = {}) {
  const locator = clean(args.locator, 2048);
  const maxAncestors = boundedInt(args.max_ancestors, 8, 16);
  const maxProperties = boundedInt(args.max_properties, 80, 160);
  return `(() => {
    const locator=${JSON.stringify(locator)},maxAncestors=${maxAncestors},maxProperties=${maxProperties};
    const text=(value,limit=500)=>String(value??'').replace(/\\s+/g,' ').trim().slice(0,limit);
    const descriptor=(owner,name)=>{let d;try{d=Object.getOwnPropertyDescriptor(owner,name);}catch{return null;}if(!d)return null;return {name:text(name,160),kind:d.get||d.set?'accessor':typeof d.value,writable:d.writable===true,enumerable:d.enumerable===true,configurable:d.configurable===true};};
    const properties=(owner)=>Object.getOwnPropertyNames(owner).slice(0,maxProperties).map(name=>descriptor(owner,name)).filter(Boolean);
    const resolve=(raw)=>{if(!raw)return null;if(raw.startsWith('text=')){const wanted=raw.slice(5).replace(/^['\"]|['\"]$/g,'').trim();return [...document.querySelectorAll('body *')].find(node=>text(node.innerText||node.textContent)===wanted)||null;}if(raw.startsWith('last=')){try{const matches=[...document.querySelectorAll(raw.slice(5))];return matches[matches.length-1]||null;}catch{return null;}}try{return document.querySelector(raw);}catch{return null;}};
    const attributes=(node)=>{const out={};for(const attr of [...(node?.attributes||[])]){const name=String(attr.name||'');if(name==='id'||name==='role'||name==='class'||name.startsWith('aria-')||name.startsWith('data-'))out[name]=text(attr.value,300);}return out;};
    const path=(node)=>{const parts=[];for(let n=node;n&&n.nodeType===1&&n!==document.documentElement;n=n.parentElement){if(n.id){parts.unshift('#'+CSS.escape(n.id));break;}const peers=n.parentElement?[...n.parentElement.children].filter(x=>x.tagName===n.tagName):[];parts.unshift(n.tagName.toLowerCase()+(peers.length>1?':nth-of-type('+(peers.indexOf(n)+1)+')':''));}return parts.join('>');};
    const node=resolve(locator);const ancestors=[];for(let n=node;n&&n.nodeType===1&&ancestors.length<maxAncestors;n=n.parentElement)ancestors.push({depth:ancestors.length,tag:String(n.tagName||'').toLowerCase(),path:path(n),text:text(n.innerText||n.textContent,300),attributes:attributes(n)});
    const prototypes=[];for(let p=node?Object.getPrototypeOf(node):null;p&&prototypes.length<6;p=Object.getPrototypeOf(p))prototypes.push({name:text(p.constructor?.name||'prototype',120),properties:properties(p)});
    const globals=Object.getOwnPropertyNames(globalThis).slice(0,maxProperties).map(name=>descriptor(globalThis,name)).filter(Boolean);
    return {ok:true,read_only:true,document:{url:location.href,title:text(document.title,240),time_origin:Number(performance.timeOrigin||0)},selection:{found:!!node,locator,path:node?path(node):'',tag:node?String(node.tagName||'').toLowerCase():'',text:node?text(node.innerText||node.textContent,500):'',attributes:node?attributes(node):{}},ancestors,prototypes,globals,budgets:{max_ancestors:maxAncestors,max_properties:maxProperties},getter_invocations:0};
  })()`;
}

async function run(context = {}, dependencies = {}) {
  const operation = context.operation?.name || "";
  if ((dependencies.platform || process.platform) !== "win32") return {ok:false,operation,failureClassification:"windows_native_shell_required"};
  if (operation !== OPERATION) return {ok:false,operation,failureClassification:"windows_cdp_runtime_operation_invalid"};
  const args = context.args || {};
  const control = dependencies.control || loadControl();
  const discover = dependencies.discover || control.discover;
  const found = await discover();
  if (!found.ok) return {ok:false,operation,failureClassification:"windows_cdp_persistent_unavailable"};
  let port; try { port = Number(JSON.parse(found.stdout).port); } catch { return {ok:false,operation,failureClassification:"windows_cdp_discovery_invalid"}; }
  const evaluated = await (dependencies.evaluate || control.evaluate)(port, control.normalizeUrl(args.target_url || ""), runtimeInspectExpression(args));
  const value = evaluated.value || {};
  const revision = crypto.createHash("sha256").update(JSON.stringify([evaluated.targetId,value.document?.url,value.document?.time_origin,value.selection?.path])).digest("hex").slice(0,16);
  return {schema:SCHEMA,operation,ok:value.ok===true,realm:"browser_cdp_persistent",targetId:evaluated.targetId,revision:`r-${revision}`,handle:value.selection?.found?`webobj:${revision}`:null,...value,proof:value.ok===true?["windows.browser.cdp.runtime.snapshot"]:[]};
}

module.exports = { OPERATION, SCHEMA, runtimeInspectExpression, run };
