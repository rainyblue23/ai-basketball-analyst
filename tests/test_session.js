const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/session.js','utf8');
function setup(status){
 const nav=[],button={disabled:false};
 const location={protocol:'http:',origin:'http://app',href:'http://app/web/index.html#/review',pathname:'/web/index.html',search:'',hash:'#/review',replace:x=>nav.push(x)};
 const window={fetch:async()=>({status,ok:status===200})};
 vm.runInNewContext(source,{window,location,URL,Promise,document:{getElementById:()=>button},alert:()=>{}});
 return {window,nav,button};
}
(async()=>{
 let s=setup(401);s.window.fetch('/api/jobs');await new Promise(setImmediate);
 assert.equal(s.nav.length,1);assert.ok(decodeURIComponent(s.nav[0]).endsWith('#/review'));
 s.window.fetch('/api/jobs');await new Promise(setImmediate);assert.equal(s.nav.length,1);
 s=setup(401);await s.window.fetch('https://other.test/api/jobs');assert.equal(s.nav.length,0);
 s=setup(200);await s.window.AIHOOP_LOGOUT();assert.equal(s.nav[0],'/web/login.html');
 s=setup(500);await s.window.AIHOOP_LOGOUT();assert.equal(s.nav.length,0);assert.equal(s.button.disabled,false);
 console.log('Session: expiry return path, single redirect, origin boundary, logout success/failure passed');
})().catch(e=>{console.error(e);process.exitCode=1});
