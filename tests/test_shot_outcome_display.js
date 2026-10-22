// Exercise the actual result-list methods and guards, including contradictory
// UNKNOWN metadata. No mutation of export values or confirmed outcome status.
const fs = require('fs'), assert = require('assert/strict');
global.window = {STORE:{}};
require('../web/data.js');
require('../web/pages/overview.js');
require('../web/pages/review.js');
require('../web/pages/highlights.js');
const D=window.D;
const rows=[
  {made:false,result:'missed',value:3},
  {made:false,result:'missed',value_assumed:true},
  {made:true,result:'made',value:2},
  {made:true,result:'made',value:3,value_assumed:true},
  {made:null,result:'unknown',value:2},
  {made:false,result:'unknown',value:2},
  {made:true,result:'unknown',value:3}
];
const frozen=JSON.stringify(rows);
for(const key of ['overview','review']){
  const method=window.PAGES[key].methods.shotValueLabel;
  assert.deepEqual(rows.map(r=>method(r)),['','','2 分','','','','']);
  const row=key==='overview'?'e':'row';
  const template=window.PAGES[key].template;
  assert(template.includes(`v-if="shotValueLabel(${row})"`));
}
for(const value of [1,2,3,null,undefined])assert.equal(D.shotLabel(value,false),'没中');
assert.equal(D.shotLabel(3,true),'中');
assert.equal(window.PAGES.highlights.methods.clipOutcome(rows[0]),'没中');
assert.equal(window.PAGES.highlights.methods.clipTitle({...rows[0],player_id:'T1',label:'三分未中'}),'T1 没中');
const span=window.PAGES.highlights.template.match(/<span v-if="([^"]+)"> · \{\{ c.value \}\} 分球<\/span>/);
assert(span);
const show=new Function('c','return '+span[1]);
assert.deepEqual(rows.map(show),[false,false,true,false,false,false,false]);
assert.equal(JSON.stringify(rows),frozen);
console.log('Outcome lists and tooltips hide missed-shot values; UNKNOWN and exports unchanged PASS');
