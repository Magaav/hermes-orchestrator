"use strict";
const assert = require("node:assert");
const runtime = require("./windows-cdp-runtime-inspect");
const expression = runtime.runtimeInspectExpression({locator:"text=hi",max_ancestors:99,max_properties:999});
assert.doesNotThrow(() => new Function(`return ${expression}`));
assert(expression.includes("Object.getOwnPropertyDescriptor"));
assert(!expression.includes("Reflect.get("));
assert(expression.includes("maxAncestors=16"));
assert(expression.includes("maxProperties=160"));
assert(expression.includes("raw.startsWith('last=')"));
(async()=>{
  const result = await runtime.run({operation:{name:runtime.OPERATION},args:{locator:"text=hi"}}, {
    platform:"win32", discover:async()=>({ok:true,stdout:'{"port":9222}'}),
    control:{normalizeUrl:(value)=>value},
    evaluate:async()=>({targetId:"page-1",value:{ok:true,read_only:true,document:{url:"https://example.test/",title:"Fixture",time_origin:7},selection:{found:true,path:"#main>span",text:"hi"},ancestors:[],prototypes:[],globals:[],budgets:{max_ancestors:8,max_properties:80},getter_invocations:0}}),
  });
  assert.strictEqual(result.ok,true); assert.strictEqual(result.handle.startsWith("webobj:"),true);
  assert.strictEqual(result.revision.startsWith("r-"),true); assert.strictEqual(result.getter_invocations,0);
  assert.deepStrictEqual(result.proof,["windows.browser.cdp.runtime.snapshot"]);
  console.log("windows CDP runtime inspect tests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
