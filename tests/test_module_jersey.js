const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync('web/data.js','utf8'),context);
const D=context.window.D;
assert.equal(D.playerLabel({jersey:0}),'0号');assert.equal(D.playerLabel({jersey:'00'}),'00号');assert.equal(D.playerLabel({jersey:13,name:'T12'}),'13号');assert.equal(D.playerLabel({name:'T14107',player_id:'T14107'}),'号码待确认');
assert.equal(D.playerLabel({name:'号码待确认',player_id:'T9',short_label:'A2'}),'A2');
vm.runInContext(fs.readFileSync('web/module-art.js','utf8'),context);
assert.equal(Object.keys(context.window.MODULE_ART).length,9);
Object.values(context.window.MODULE_ART).forEach(x=>assert(x.includes('<svg')));
const home=fs.readFileSync('web/pages/home.js','utf8');assert(home.includes('v-html="c.art"'));assert(!home.includes('<img class="module-cover"'));
const overlay=fs.readFileSync('web/detection-overlay.js','utf8');assert(overlay.includes('identityLabel(id)'));assert(!overlay.includes("'球员 '+p.id"));
console.log('inline module artwork / jersey labels: PASS');

vm.runInContext(fs.readFileSync('web/court.js','utf8'),context);
const svg=context.window.Court.tacticsPlayersLayer({players:[['T1','home',1,2]]},{},{players:[{player_id:'T1',jersey:'00'}]});
assert(svg.includes('00号'));assert(!svg.includes('<title>T1'));assert(!fs.readFileSync('web/court.js','utf8').includes('String(pid).slice(-2)'));
