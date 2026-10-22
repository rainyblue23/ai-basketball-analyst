const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const context={window:{},console};vm.createContext(context);vm.runInContext(fs.readFileSync('web/data.js','utf8'),context);context.D=context.window.D;vm.runInContext(fs.readFileSync('web/court.js','utf8'),context);vm.runInContext(fs.readFileSync('web/pages/tactics.js','utf8'),context);
assert.equal(context.D.playerLabel({short_label:'B144'}),'B144');assert.equal(context.D.tacticsPlayerLabel({player_id:'T12'}),'T12');assert.equal(context.D.tacticsPlayerLabel({jersey:12,player_id:'T1'}),'12号');
const a={t:0,segment:0,players:[['T1','home',0,-3]]},b={t:.5,segment:0,players:[['T1','home',1,-3]]};
assert.equal(context.interpolateTacticsFrame(a,b,.25).players[0][2],.5);
assert.equal(context.interpolateTacticsFrame(a,null,10).players.length,0);
assert.equal(context.interpolateTacticsFrame(a,{...b,segment:1},.25),a);
assert.equal(context.interpolateTacticsFrame(a,{...b,players:[]},.25),a);
assert.equal(context.interpolateTacticsFrame(a,{...b,players:[['T1','home',14,-3]]},.25).players[0][2],0);
const svg=context.window.Court.tacticsPlayersLayer({players:[['T1','home',0,-2],['T2','away',0,2]]},{},{view:'full',players:[]});
assert(svg.includes('viewBox="0 0 18 31"'));assert(svg.includes('cy="3.5"')&&svg.includes('cy="27.5"'));assert(!svg.includes('号码待确认'));
console.log('tactical labels, full-court geometry and bounded display interpolation PASS');
const unknown={t:0,players:Array.from({length:7},(_,i)=>['T'+i,'unknown',i,4])};
assert.equal(context.tacticsPopulationIssue(unknown),false);
assert.equal(context.tacticsPopulationIssue({...unknown,players:unknown.players.map(p=>[p[0],'home',p[2],p[3]])}),true);
assert.equal(context.tacticsPopulationIssue({...unknown,players:Array.from({length:11},(_,i)=>['T'+i,'unknown',i,4])}),true);
const quality=context.window.PAGES.tactics.computed.frameQuality.call({frames:[unknown]});
assert.equal(quality.valid,1);
const groupSVG=context.window.Court.tacticsPlayersLayer({players:[['T1','team_a',0,-2],['T2','team_b',0,2],['T3','unknown',2,3]]},{},{view:'full',players:[]});
assert(groupSVG.includes('#2f6fed')&&groupSVG.includes('#f2762e')&&groupSVG.includes('#64748b'));
assert(groupSVG.includes('分组A（主客未核实）')&&groupSVG.includes('分队未知'));
assert(groupSVG.includes('fill="#172033"')&&groupSVG.includes('paint-order="stroke"'));

// Changing observed head count or camera segment must not produce a false
// continuous tactical trend. Point values retain the observed player count.
const component=context.window.PAGES.tactics;
const chart=component.computed.spacingOption.call({
  tac:{config:{frame_step:1},spacing:{timeline:[
    {t:0,team:'team_a',area:4,n:2,segment:0},
    {t:1,team:'team_a',area:8,n:3,segment:0},
    {t:2,team:'team_a',area:9,n:3,segment:1},
    {t:5,team:'team_a',area:10,n:3,segment:1}
  ]}},metric:'area',spacingObservedSubset:true,teams:['team_a','team_b'],duration:6,
  METRICS:[{key:'area',label:'站位面积'}],teamName:s=>s
});
assert.deepEqual(JSON.parse(JSON.stringify(chart.series[0].data)),[
  [0,4,2],[.5,null],[1,8,3],[1.5,null],[2,9,3],[3.5,null],[5,10,3]
]);
assert(chart.tooltip.formatter([{seriesName:'<img>',value:[1,8,3]}]).includes('可见 3 人'));
assert(!chart.tooltip.formatter([{seriesName:'<img>',value:[1,8,3]}]).includes('<img>'));
assert.equal(chart.series[0].connectNulls,false);
