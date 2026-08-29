"use strict";
const assert = require("node:assert");
const control = require("./windows-cdp-control");
assert(control.inspectExpression(80).includes("semanticNodes(80)"));
assert.doesNotThrow(() => new Function(`return ${control.inspectExpression(80)}`));
assert(control.inspectExpression(80,"Laura").includes('const query="Laura"'));
assert(control.inspectExpression(80,"","[contenteditable=true]").includes('const selector="[contenteditable=true]"'));
assert(control.inspectExpression(80,"Laura","").includes("actionLocator:actionPath(n,actionNode||n)"));
assert(control.inspectExpression(80,"","[contenteditable=true]").includes("target:targetFingerprint(n)"));
assert(control.inspectExpression(80).includes("editable_targets"));
assert(control.actExpression({locator:"text=Laura",action:"click",expect:{property:"name",equals:"Laura"}}).includes("actionLocator:actionPath(n)"));
assert(control.inspectExpression(80,"Laura").includes("Number(inViewport(b))-Number(inViewport(a))"));
assert(control.actExpression({locator:"#message",action:"set_value",value:"hi",expect:{property:"value",equals:"hi"}}).includes("postconditionVerified"));
assert(control.actExpression({locator:"text=Laura",action:"click",expect:{property:"page_text_contains",equals:"Laura"}}).includes("locator.startsWith('text=')"));
assert(control.targetPointExpression("text=Laura").includes("scrollIntoView"));
assert(control.targetPointExpression("text=Laura").includes("elementFromPoint"));
assert.doesNotThrow(() => new Function(`return ${control.targetPointExpression("text=Laura")}`));
assert.doesNotThrow(() => new Function(`return ${control.targetContractExpression("#composer",{role:"textbox",editable:true,scope_locator:"#main",name_contains:"Laura"})}`));
assert.doesNotThrow(() => new Function(`return ${control.assertionStateExpression([{id:"sent",selector:".outgoing",property:"last_text",transition:"became_equal",equals:"hi"}])}`));
assert(control.assertionStateExpression([{id:"sent",selector:"text=hi",property:"count",transition:"count_increased"}]).includes("raw.startsWith('text=')"));
assert.deepStrictEqual(control.completionProof(
  [{id:"sent",property:"last_text",transition:"became_equal",equals:"hi"},{id:"composer",property:"value",transition:"became_equal",equals:""}],
  [{id:"sent",value:"old"},{id:"composer",value:"hi"}],
  [{id:"sent",value:"hi"},{id:"composer",value:""}],
), {ok:true,assertions:[
  {id:"sent",property:"last_text",transition:"became_equal",expected:"hi",before:"old",after:"hi",passed:true},
  {id:"composer",property:"value",transition:"became_equal",expected:"",before:"hi",after:"",passed:true},
]});
assert(control.actExpression({locator:"text=Laura",action:"click",expect:{property:"page_text_contains",equals:"Laura"}}).includes("changed.length>0"));
assert(control.actExpression({steps:[{locator:"#message",action:"set_value",value:"hi"},{locator:"#message",action:"key",key:"Enter"}],expect:{property:"page_text_contains",equals:"hi"}}).includes("const steps="));
assert.doesNotThrow(() => new Function(`return ${control.actExpression({locator:"text=Laura",action:"click",expect:{property:"page_text_contains",equals:"Laura"}})}`));
(async()=>{
  const attrs = (values={}) => ({getAttribute:(name)=>Object.prototype.hasOwnProperty.call(values,name)?values[name]:null,hasAttribute:(name)=>Object.prototype.hasOwnProperty.call(values,name)});
  const searchBox = {nodeType:1,tagName:"INPUT",children:[],value:"Laura",innerText:"",isContentEditable:false,disabled:false,getClientRects:()=>[1],getBoundingClientRect:()=>({left:0,top:0,width:100,height:20}),...attrs()};
  const contactText = {nodeType:1,tagName:"SPAN",children:[],innerText:"Laura",isContentEditable:false,disabled:false,getClientRects:()=>[1],getBoundingClientRect:()=>({left:40,top:40,width:20,height:20}),scrollIntoView(){},focus(){textDocument.activeElement=this;},contains:(node)=>node===contactText,...attrs()};
  const textDocument = {activeElement:null,querySelectorAll:()=>[searchBox,contactText],querySelector:()=>null,elementFromPoint:()=>contactText};
  const resolveText = new Function("document","getComputedStyle","innerWidth","innerHeight",`return ${control.targetPointExpression("text=Laura")}`);
  const resolvedText = resolveText(textDocument,()=>({cursor:"default"}),1000,800);
  assert.strictEqual(resolvedText.ok,true); assert.strictEqual(resolvedText.x,50); assert.strictEqual(textDocument.activeElement,contactText);
  const semanticAttrs = (values={}) => ({getAttribute:(name)=>Object.prototype.hasOwnProperty.call(values,name)?values[name]:null,hasAttribute:(name)=>Object.prototype.hasOwnProperty.call(values,name),closest:()=>null});
  const targetDocument = {querySelectorAll:()=>[],activeElement:null};
  const searchTarget = {nodeType:1,tagName:"INPUT",type:"text",value:"",innerText:"",isContentEditable:false,disabled:false,getClientRects:()=>[1],getBoundingClientRect:()=>({x:20,y:20,left:20,top:20,width:240,height:30}),...semanticAttrs({role:"textbox","aria-label":"Laura search"})};
  const composerTarget = {nodeType:1,tagName:"DIV",value:undefined,innerText:"",isContentEditable:true,disabled:false,getClientRects:()=>[1],getBoundingClientRect:()=>({x:700,y:700,left:700,top:700,width:260,height:40}),...semanticAttrs({role:"textbox","aria-label":"Message Laura"})};
  const mainScope = {contains:(node)=>node===composerTarget};
  const targetContract = new Function("document","getComputedStyle","innerWidth","innerHeight",`return ${control.targetContractExpression("#target",{role:"textbox",editable:true,scope_locator:"#main",name_contains:"Laura"})}`);
  targetDocument.querySelector=(selector)=>selector==="#target"?searchTarget:selector==="#main"?mainScope:null;
  const rejectedSearch=targetContract(targetDocument,()=>({cursor:"text"}),1000,900);
  assert.strictEqual(rejectedSearch.ok,false); assert.strictEqual(rejectedSearch.code,"browser_target_contract_mismatch"); assert(rejectedSearch.mismatch.includes("scope"));
  targetDocument.querySelector=(selector)=>selector==="#target"?composerTarget:selector==="#main"?mainScope:null;
  const acceptedComposer=targetContract(targetDocument,()=>({cursor:"text"}),1000,900);
  assert.strictEqual(acceptedComposer.ok,true); assert.strictEqual(acceptedComposer.actual.zone,"right-bottom");
  const stalePage = await control.interact(9222,"https://example.test",{page_target_id:"old",steps:[{locator:"#composer",action:"set_value",value:"hi"}],assertions:[]},1000,async(_port,_target,handler)=>handler(async()=>{throw new Error("must_not_dispatch");},{id:"new"}));
  assert.strictEqual(stalePage.value.ok,false); assert.strictEqual(stalePage.value.code,"browser_page_target_mismatch");
  const methods=[]; const runtimeValues=[
    {url:"https://example.test/",page_text:"before",name:"Laura",value:"",focused:false},
    {ok:true,x:20,y:30,name:"Laura",value:"",focused:false},
    {ok:true},
    {ok:true,url:"https://example.test/",text:"Laura selected",page_text:"Laura selected",controls:[]},
    {ok:true,name:"Laura",value:"",focused:false},
  ];
  const session = async (_port,_target,handler) => handler(async(method,params)=>{methods.push({method,params});if(method==="Runtime.evaluate")return {result:{result:{value:runtimeValues.shift()}}};return {result:{}};},{id:"t1"});
  const semanticClick = await control.interact(9222,"https://example.test",{locator:"text=Laura",action:"click",expect:{property:"page_text_contains",equals:"Laura"}},1000,session);
  assert.strictEqual(semanticClick.value.ok,true); assert.deepStrictEqual(semanticClick.value.changed,["page_text"]);
  assert.deepStrictEqual(methods.filter(item=>item.method==="Input.dispatchMouseEvent").map(item=>item.params.type),["mouseMoved","mousePressed","mouseReleased"]);
  assert.strictEqual(methods.find(item=>item.params.type==="mousePressed").params.x,20);
  const unchangedValues=[
    {url:"https://example.test/",page_text:"same",name:"message",value:"hi",focused:true},
    {ok:true,name:"message",value:"hi",focused:true},
    {ok:true},
    {ok:true,url:"https://example.test/",text:"same",page_text:"same",controls:[]},
    {ok:true,name:"message",value:"hi",focused:true},
  ];
  const unchangedSession = async (_port,_target,handler) => handler(async(method)=>method==="Runtime.evaluate"?{result:{result:{value:unchangedValues.shift()}}}:{result:{}},{id:"t2"});
  const unchanged = await control.interact(9222,"https://example.test",{locator:"#message",action:"set_value",value:"hi",expect:{property:"value",equals:"hi"}},1000,unchangedSession);
  assert.strictEqual(unchanged.value.ok,false); assert.strictEqual(unchanged.value.code,"browser_postcondition_preexisting");
  const preexistingValues=[
    {url:"https://example.test/",page_text:"Laura before",name:"Laura",value:"",focused:false},
    {ok:true,x:20,y:30,name:"Laura",value:"",focused:false},
    {ok:true},
    {ok:true,url:"https://example.test/",text:"Laura after",page_text:"Laura after",controls:[]},
    {ok:true,name:"Laura",value:"",focused:false},
  ];
  const preexistingSession = async (_port,_target,handler) => handler(async(method)=>method==="Runtime.evaluate"?{result:{result:{value:preexistingValues.shift()}}}:{result:{}},{id:"t-preexisting"});
  const preexisting = await control.interact(9222,"https://example.test",{locator:"text=Laura",action:"click",expect:{property:"page_text_contains",equals:"Laura"}},1000,preexistingSession);
  assert.strictEqual(preexisting.value.ok,false); assert.strictEqual(preexisting.value.code,"browser_postcondition_preexisting");
  const keyMethods=[]; const transactionValues=[
    {url:"https://example.test/",page_text:"before",name:"message",value:"",focused:false},
    {ok:true,name:"message",value:"hi",focused:true}, {ok:true},
    {ok:true,name:"message",value:"hi",focused:true}, {ok:true},
    {ok:true,url:"https://example.test/",text:"before hi",page_text:"before hi",controls:[]},
    {ok:true,name:"message",value:"",focused:true},
  ];
  const transactionSession = async (_port,_target,handler) => handler(async(method,params)=>{keyMethods.push({method,params});return method==="Runtime.evaluate"?{result:{result:{value:transactionValues.shift()}}}:{result:{}};},{id:"t3"});
  const trustedTransaction = await control.interact(9222,"https://example.test",{steps:[{locator:"#message",action:"set_value",value:"hi"},{locator:"#message",action:"key",key:"Enter"}],expect:{property:"page_text_contains",equals:"hi"}},1000,transactionSession);
  assert.strictEqual(trustedTransaction.value.ok,true);
  assert.deepStrictEqual(keyMethods.filter(item=>item.method==="Input.dispatchKeyEvent").map(item=>item.params.type),["rawKeyDown","keyUp"]);
  assert.deepStrictEqual(control.recoveryLens({locator:"text=Type a message",action:"set_value"}),{queryText:"Type a message",querySelector:"[contenteditable=true],textarea,input"});
  const failedStepValues=[
    {url:"https://example.test/",page_text:"Laura",name:"",value:"",focused:false},
    {ok:true,x:20,y:30,name:"Laura",value:"",focused:false},
    {ok:true},
    {ok:false,code:"browser_ref_missing"},
    {ok:true,matches:[],selector_matches:[{ref:"s1",locator:"#composer",actionLocator:"#composer",role:"textbox",name:"Escrever mensagem",editable:true}]},
  ];
  const failedStepSession = async (_port,_target,handler) => handler(async(method)=>method==="Runtime.evaluate"?{result:{result:{value:failedStepValues.shift()}}}:{result:{}},{id:"t-failed-step"});
  const failedStep = await control.interact(9222,"https://example.test",{steps:[{locator:"text=Laura",action:"click"},{locator:"text=Type a message",action:"set_value",value:"hi"}],expect:{property:"page_text_contains",equals:"hi"}},1000,failedStepSession);
  assert.strictEqual(failedStep.value.ok,false); assert.strictEqual(failedStep.value.failedStepIndex,1);
  assert.strictEqual(failedStep.value.failedAction,"set_value"); assert.strictEqual(failedStep.value.failedLocator,"text=Type a message");
  assert.strictEqual(failedStep.value.recovery.queryText,"Type a message"); assert.strictEqual(failedStep.value.recovery.selectorMatches[0].actionLocator,"#composer");
  const inspect = await control.run({operation:{name:control.INSPECT_OPERATION},args:{target_url:"https://web.whatsapp.com",max_elements:80,query_text:"Laura",query_selector:"[contenteditable=true]"}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),evaluate:async()=>({targetId:"t1",value:{ok:true,url:"https://web.whatsapp.com/",title:"WhatsApp",controls:[{ref:"c1",locator:"#laura",name:"Laura"}],editable_targets:[{ref:"e1",locator:"#message",scopeLocator:"#main",role:"textbox",name:"Message Laura"}],matches:[{ref:"t1",locator:"#laura",name:"Laura"}],selector_matches:[{ref:"s1",locator:"#message",editable:true}],text:"Laura"}})});
  assert.strictEqual(inspect.ok,true); assert.strictEqual(inspect.controls[0].name,"Laura"); assert.strictEqual(inspect.matches[0].ref,"t1"); assert.strictEqual(inspect.selectorMatches[0].ref,"s1");
  assert.strictEqual(inspect.editableTargets[0].scopeLocator,"#main");
  const act = await control.run({operation:{name:control.ACT_OPERATION},args:{locator:"#laura",action:"click",expect:{property:"name",equals:"Laura"}}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),interact:async()=>({targetId:"t1",value:{ok:true,postconditionVerified:true,observed:{name:"Laura"}}})});
  assert.strictEqual(act.ok,true); assert.deepStrictEqual(act.proof,["windows.browser.cdp.action.observed"]);
  const transaction = await control.run({operation:{name:control.ACT_OPERATION},args:{steps:[{locator:"#message",action:"set_value",value:"hi"},{locator:"#message",action:"key",key:"Enter"}],expect:{property:"page_text_contains",equals:"hi"}}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),evaluate:async()=>({targetId:"t1",value:{ok:true,postconditionVerified:true,observed:{page_text:"hi",controls:[]}}})});
  assert.strictEqual(transaction.action,"transaction"); assert.strictEqual(transaction.stepCount,2);
  const failedTransaction = await control.run({operation:{name:control.ACT_OPERATION},args:{steps:[{locator:"#laura",action:"click"},{locator:"text=Type a message",action:"set_value",value:"hi"}],expect:{property:"page_text_contains",equals:"hi"}}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),interact:async()=>({targetId:"t1",value:{ok:false,code:"browser_ref_missing",failedStepIndex:1,failedAction:"set_value",failedLocator:"text=Type a message",recovery:{queryText:"Type a message",querySelector:"[contenteditable=true],textarea,input",matches:[],selectorMatches:[{locator:"#composer",editable:true}]}}})});
  assert.strictEqual(failedTransaction.failedStepIndex,1); assert.strictEqual(failedTransaction.failedLocator,"text=Type a message");
  assert.strictEqual(failedTransaction.recovery.selectorMatches[0].locator,"#composer");
  const invalidKey = await control.run({operation:{name:control.ACT_OPERATION},args:{locator:"#message",action:"key",key:"",expect:{property:"focused",equals:true}}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'})});
  assert.strictEqual(invalidKey.failureClassification,"windows_cdp_action_invalid");
  const composerContract={role:"textbox",editable:true,scope_locator:"#main",name_contains:"message"};
  const procedure = await control.run({operation:{name:control.PROCEDURE_OPERATION},args:{page_target_id:"t1",steps:[{locator:"#composer",action:"set_value",value:"hi",target_contract:composerContract},{locator:"#composer",action:"key",key:"Enter",target_contract:composerContract}],assertions:[{id:"sent",selector:".outgoing",scope_locator:"#main",property:"last_text",transition:"became_equal",equals:"hi"}]}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),interact:async()=>({targetId:"t1",value:{ok:true,action:{dispatched:true,steps:[]},observation:{url:"https://example.test"},completion_proof:{ok:true,assertions:[{id:"sent",passed:true}]}}})});
  assert.strictEqual(procedure.ok,true); assert.deepStrictEqual(procedure.proof,["windows.browser.cdp.procedure.completed"]);
  const uncertainProcedure = await control.run({operation:{name:control.PROCEDURE_OPERATION},args:{page_target_id:"t1",steps:[{locator:"#composer",action:"set_value",value:"hi",target_contract:composerContract},{locator:"#composer",action:"key",key:"Enter",target_contract:composerContract}],assertions:[{id:"sent",selector:"text=hi",scope_locator:"#main",property:"count",transition:"count_increased"}]}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),interact:async()=>({targetId:"t1",value:{ok:false,code:"commit_unknown",action:{dispatched:true,steps:[]},completion_proof:{ok:false}}})});
  assert.strictEqual(uncertainProcedure.ok,false); assert.strictEqual(uncertainProcedure.failureClassification,"commit_unknown");
  const unboundProcedure = await control.run({operation:{name:control.PROCEDURE_OPERATION},args:{steps:[{locator:"#composer",action:"set_value",value:"hi"}],assertions:[{id:"sent",selector:"text=hi",property:"count",transition:"count_increased"}]}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'})});
  assert.strictEqual(unboundProcedure.failureClassification,"windows_cdp_procedure_invalid");
  const closed = await control.run({operation:{name:control.STATUS_OPERATION},args:{}}, {platform:"win32",discover:async()=>({ok:false,error:"persistent_cdp_active_port_not_found"})});
  assert.strictEqual(closed.ok,true); assert.strictEqual(closed.state,"closed"); assert.strictEqual(closed.next,"client.windows.browser.cdp.default.open");
  const pageMissing = await control.run({operation:{name:control.STATUS_OPERATION},args:{}}, {platform:"win32",discover:async()=>({ok:true,stdout:'{"port":9222}'}),requestJson:async()=>[]});
  assert.strictEqual(pageMissing.ok,true); assert.strictEqual(pageMissing.state,"open_no_page"); assert.strictEqual(pageMissing.cause,"windows_cdp_page_missing");
  assert.strictEqual(pageMissing.next,"client.windows.browser.cdp.default.open");
  console.log("windows CDP control proof tests passed");
})().catch((error)=>{console.error(error);process.exitCode=1;});
