// Results show only the two labels; unconfirmed source data stays unchanged.
const assert=require('node:assert/strict');
global.window={STORE:{}};
require('../web/data.js');
require('../web/pages/overview.js');
require('../web/pages/review.js');
require('../web/pages/highlights.js');
require('../web/detection-overlay.js');
const D=window.D;
const rows=[
  {t:1,made:true,result:'made',value:2},
  {t:2,made:false,result:'missed',value:3},
  {t:3,made:null,result:'unknown',value:3,suggested_made:true,evidence:'cross_interpolated'},
  {t:4,made:null,result:'unknown',value:2,suggested_made:false},
  {t:5,made:null,result:'unknown',value:2},
  {t:6,made:true,result:'unknown',value:3},
  {t:7,made:null,result:'unknown',value:3,suggested_made:true,review_reason:'cross_hoop_uncertain'}
];
const frozen=JSON.stringify(rows);
assert.deepEqual(rows.map(r=>D.shotDisplay(r).label),[
  '中','没中','','','','','']);
assert.deepEqual(rows.map(D.isUnknown),[false,false,true,true,true,true,true]);
assert(rows.slice(2).every(r=>D.shotValueLabel(r)===''));
assert(rows.slice(2).every(r=>D.shotDisplay(r).made===null && !D.shotDisplay(r).resolved));
const page=window.PAGES.overview;
const v={...page.data(),game:{timeline:rows},filterTeam:'all',filterMade:'all'};
for(const [k,fn] of Object.entries(page.methods))v[k]=fn.bind(v);
assert.deepEqual(page.computed.shotCounts.call(v),{total:7,made:1,miss:1,pending:5});
v.filterMade='made';assert.deepEqual(page.computed.timeline.call(v).map(r=>r.t),[1]);
v.filterMade='miss';assert.deepEqual(page.computed.timeline.call(v).map(r=>r.t),[2]);
v.filterMade='all';
const results=page.computed.timeline.call(v),other=page.computed.unresolvedShots.call(v);
assert.deepEqual([...results,...other].map(r=>r.t).sort((a,b)=>a-b),rows.map(r=>r.t),'No input observation may disappear');
assert.deepEqual(other.map(r=>r.t),[3,4,5,6,7]);
assert(!page.template.includes('label="unknown"'));
assert(!page.template.includes('shotCounts.unknown'));
assert(page.template.includes('resultLabel(e)'));
assert(!page.template.includes('推测')&&!page.template.includes('暂定'));
assert(!page.template.includes('其他回看时间'));
assert(!page.template.includes('证据不足'));
assert(!page.template.includes('shot-review-times'));
assert(!page.template.includes('unresolvedShots'));
for(const name of ['overview','review'])
  assert.deepEqual(rows.map(r=>window.PAGES[name].methods.resultLabel(r)),rows.map(r=>D.shotDisplay(r).label));
const high=window.PAGES.highlights.methods;
assert.deepEqual(rows.map(r=>high.clipOutcome(r)),['中','没中','','','','','']);
assert(!window.PAGES.review.template.includes('<el-option label="未知"'));
const replay=window.COMPONENTS['replay-tools'].methods;
assert.deepEqual(rows.map(r=>replay.label(r)),rows.map(r=>D.shotDisplay(r).label));
let warnings=[],writes=0;
window.API={addManualShot(){writes++;throw Error('No choice must not submit');}};
window.PAGES.review.methods.addManual.call({canSubmit:true,manual:{result:''},$message:{warning:s=>warnings.push(s)}});
assert.equal(writes,0);assert.deepEqual(warnings,['请选择中或没中']);
assert.deepEqual(D.shotsFromTimeline({timeline:rows}).map(r=>r.t),[1,2]);
assert.equal(JSON.stringify(rows),frozen,'Display must never overwrite raw unknown/made/suggestions');
console.log('Two literal labels; no other-times section; raw records and statistics unchanged PASS');
