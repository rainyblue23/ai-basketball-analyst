const assert=require('node:assert/strict');
global.window={STORE:{}};
require('../web/data.js');global.D=window.D;
require('../web/court.js');require('../web/pages/tactics.js');
const graph={nodes:[{id:'a',jersey:7,team:'home'},{id:'b',jersey:16,team:'home'},
 {id:'c',jersey:9,team:'away'},{id:'d',jersey:10,team:'away'}],
 edges:[{source:'a',target:'b',value:3},{source:'b',target:'a',value:1},
 {source:'c',target:'d',value:2}]};
let html=window.Court.passNetLayer(graph,{focus:'a'});
assert.match(html,/data-player="a" data-selected="true"/);
assert.match(html,/cx="320" cy="240" r="42"/);
assert.match(html,/data-player="b"/);
assert.doesNotMatch(html,/data-player="c"/);
assert.match(html,/7号/);assert.match(html,/16号/);
assert.match(html,/marker-end=/);
html=window.Court.passNetLayer(graph,{});
assert.match(html,/fill="#2f6fed"/);assert.match(html,/fill="#f2762e"/);
assert.match(html,/data-player="c"/);
const p=window.PAGES.tactics, vm={S:{players:[{player_id:'a',jersey:7}]},
 netTeam:'all',netFocus:'a',tac:{pass_network:{home:{nodes:graph.nodes.slice(0,2),edges:graph.edges.slice(0,2)},
 away:{nodes:graph.nodes.slice(2),edges:graph.edges.slice(2)}}}};
vm.net=p.computed.net.call(vm);
assert.equal(vm.net.nodes.length,4);
assert.equal(vm.net.nodes[0].jersey,7);
assert.equal(p.computed.netEdges.call(vm).length,2);
let prevented=false;
p.methods.selectNetPlayer.call(vm,{type:'click',target:{closest:()=>({getAttribute:()=> 'b'})},preventDefault(){prevented=true;}});
assert.equal(vm.netFocus,'b');assert.ok(prevented);
console.log('Pass network focus, team colors and related edges passed');
