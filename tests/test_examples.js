const assert=require('assert'),fs=require('fs'),vm=require('vm');
const ctx={window:{PAGES:{},API:{base:'/base'},D:{mmss:t=>String(t)}},location:{hash:''}};
vm.runInNewContext(fs.readFileSync('web/pages/examples.js','utf8'),ctx);
const page=ctx.window.PAGES.examples;
assert(page.template.includes('结果未知'));
assert(page.template.includes(':disabled="!row.ready || !!opening"'));
assert(page.template.includes('role="alert"'));
assert(page.template.includes('样例只供查看'));
let calls=0;ctx.window.APP_LOAD_JOB=id=>{calls++;assert.equal(id,'example_one');return Promise.resolve();};
let state={opening:'',error:''};
page.methods.open.call(state,{id:'one',job_id:'example_one',ready:false});assert.equal(calls,0);
page.methods.open.call(state,{id:'one',job_id:'example_one',ready:true});assert.equal(calls,1);
const appSource=fs.readFileSync('web/app.js','utf8');assert(appSource.includes('STORE.game = D.normalizeGame(game'));assert(appSource.includes('aihoop_active_example'));assert(appSource.includes('game: function () { return this.state.game; }'));
const home=fs.readFileSync('web/pages/home.js','utf8');assert(home.includes("'modules/' + m.key + '.svg'"));
assert(fs.readFileSync('web/editorial.css','utf8').includes("background-image: url('./img/hero_court.jpg')"));
for(const key of ['upload','overview','review','stats','shotchart','tactics','highlights','report','examples']) {
 const svg=fs.readFileSync('web/img/modules/'+key+'.svg','utf8');assert(svg.includes('<svg'));assert(!svg.includes('<image'));
}
ctx.window.STORE={jobId:'example_one',backendOk:true,demoMode:false};
vm.runInNewContext(fs.readFileSync('web/pages/review.js','utf8'),ctx);
const review=ctx.window.PAGES.review;
assert.equal(review.computed.canSubmit.call({S:ctx.window.STORE}),false);
assert.equal(review.computed.isExample.call({S:ctx.window.STORE}),true);
assert(review.template.includes(':disabled="isExample" @click="correct(row, true, row.value)"'));
assert(review.template.includes('class="card" v-if="!isExample"'));
Promise.resolve().then(()=>{assert.equal(ctx.location.hash,'#/overview');console.log('Examples navigation, vector assets and pending guards passed');});
