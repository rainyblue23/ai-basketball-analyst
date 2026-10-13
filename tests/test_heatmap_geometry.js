const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const ctx = vm.createContext({});
ctx.window = ctx;
for (const file of ['data.js', 'court.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web', file), 'utf8'), ctx);
}
const C = ctx.window.Court;
const D = ctx.window.D;
function pointEqual(actual, expected) {
  assert.equal(actual.u, expected[0]);
  assert.equal(actual.v, expected[1]);
}
// A/B layups must sit at the drawn basket, rather than the left sideline.
pointEqual(C.mapXY('half', 0, 1.575), [7.5,1.575]);
pointEqual(C.mapXY('half', 0, -1.575), [7.5,1.575]);
pointEqual(C.mapXY('half', -4,-5), [11.5,5]);
// The full view unfolds baseline distances back to the two actual baskets.
pointEqual(C.mapXY('full', 0, -1.575), [7.5,1.575]);
pointEqual(C.mapXY('full', 0, 1.575), [7.5,26.425]);
const grid = D.buildGrid([{x:-4,y:-5,made:true},{x:4,y:5,made:false}],1);
assert.equal(grid[5][11].att,2);
assert.equal(grid[5][11].made,1);
assert.equal(grid.flat().reduce((n,c)=>n+c.att,0),2);
// The free throw line is 5.8m from the baseline, independently of hoop height.
const svg = C.courtSVG({view:'half'});
assert.ok(svg.includes('cy="7.1" r="1.8"'), 'FT circle must be at 5.8m plus padding');
const shot = C.shotLayer([{x:0,y:1.575,made:true,value:2,t:1}],{view:'half'});
assert.ok(shot.includes('cx="8.8" cy="2.88"'), 'Layup must align with the drawn basket');
console.log('Heatmap geometry: 10 reference checks passed');
