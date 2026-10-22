const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const start = source.indexOf('window.APP_REFRESH_RESULTS = function');
const end = source.indexOf('window.APP_TACTICS =', start);
let applied;
const state = {jobId:'same-job',backendOk:true,players:[],report:null,highlights:[]};
const context = {STATE:state,Promise,applyGame:(g,p,c)=>{applied={g,c};},window:{API:{
  game:async id=>({meta:{calibration_valid:true},id}),
  shotchart:async id=>({all:{points:[{x:1,y:2}]},id})
}}};
vm.runInNewContext(source.slice(start,end),context);
(async()=>{
  await context.window.APP_REFRESH_RESULTS();
  assert.equal(applied.g.meta.calibration_valid,true);
  assert.equal(applied.c.all.points.length,1);
  applied=null;
  context.window.API.game=async()=>{state.jobId='other-job';return {};};
  await context.window.APP_REFRESH_RESULTS();
  assert.equal(applied,null,'discard response after user switches matches');
  console.log('results refresh passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
