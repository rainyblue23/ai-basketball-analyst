const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
function scan(template){
 const tokens=template.match(/<!--[\s\S]*?-->|{{[\s\S]*?}}|<(?:[^>"']|"[^"]*"|'[^']*')*>|[^<{]+|[<{]/g)||[];
 const stack=[],visible=[],secondary=[],intro=[];let offset=0;
 const hiddenTags=new Set(['copy-note','el-tooltip','el-popover','el-collapse','el-dialog','details']);
 for(const token of tokens){
  if(token.startsWith('<!--'))continue;
  if(token.startsWith('{{'))continue; // runtime values are separately reviewed, not invented counts
  const m=token.match(/^<(\/?)([\w-]+)/);
  if(m){
   const name=m[2];
   if(m[1]){if(stack.length && stack.at(-1).name===name)stack.pop();continue;}
   const hidden=stack.some(x=>x.hidden);
   if(name==='copy-note'&&!hidden){const label=token.match(/\blabel="([^"]*)"/);assert.ok(label&&label[1],'说明必须有可见入口');visible.push(label[1]);}
   // Static alert strings also appear to the user; do not hide them from the budget.
   if(!hidden&&!hiddenTags.has(name))for(const a of token.matchAll(/(?:^|\s)(title|description|placeholder|active-text)="([^"]*)"/g))visible.push(a[2]);
   if(!token.endsWith('/>')&&!['input','img','br','hr','source','meta','link'].includes(name))stack.push({name,hidden:hidden||hiddenTags.has(name),explanation:/\b(?:hint|sub|muted|page-sub)\b/.test(token)});
   continue;
  }
  const text=token.trim();if(!text)continue;
  if(stack.some(x=>x.hidden))secondary.push(text);else{visible.push(text);if(stack.some(x=>x.explanation))intro.push(text);}
 }
 const count=s=>(s.match(/[\u4e00-\u9fff]/g)||[]).length;
 return {chars:count(visible.join('')),long:visible.filter(x=>count(x)>=40),visible,secondary,intro,explanationChars:count(intro.join(''))};
}
function load(){const c={window:{STORE:{},PAGES:{},D:{}},console};vm.createContext(c);for(const f of fs.readdirSync(path.join(root,'web/pages')).filter(f=>f.endsWith('.js')))vm.runInContext(fs.readFileSync(path.join(root,'web/pages',f),'utf8'),c);return c.window.PAGES;}
/* 全站静态文案预算。单位 = 可见文案的汉字数（藏在 copy-note 弹层里的长文不计）。
   2026-10-05 按用户要求做过一轮「灰色说明压短 + 去掉每段后面那个『说明』按钮」：
     * 正文 ≤40 汉字的说明从弹层搬到页面**直接显示** → 可见字数上升，但页面上不再到处挂小按钮；
       用户的两条要求（灰字要短、按钮要少）本身是互相拉扯的，这里取「一行为限 + 少按钮」。
     * 长解释一律留在 copy-note 里（不可见、不计入预算）。
   所以下面每页的数字按**本轮实测 + 约 8% 余量**重新定基线，作用是**防止以后继续膨胀**，
   不再当作"必须压到某个数以下"的设计目标。真正硬的约束是：单条可见文案不得 ≥40 汉字
   （灰色说明必须是一行）、常驻说明总量有上限、口径关键词必须还在。 */
const budgets={upload:580,overview:620,report:200,highlights:285,shotchart:305,review:230,tactics:285,home:205};
/* 常驻说明（.hint/.sub/.muted 里的可见文字）上限。默认 120；
   总览页要放"数据可用性/未知"这类必须常驻的口径，上传页是唯一的主操作页（数据源+参数+标定+进度），
   战术页有坐标口径说明 —— 这三页单独放宽，其余页仍按 120 卡。 */
const EXPLAIN_CAP={overview:270,upload:175,tactics:175};
const results={};for(const [key,page] of Object.entries(load()))results[key]=scan(page.template);
if(require.main===module){
 let total=0;for(const [key,r] of Object.entries(results)){total+=r.chars;console.log(key,r.chars,'long',r.long.length,'explanations',r.explanationChars);}
 console.log('Total',total);
 if(!process.argv.includes('--report')){
 assert.ok(total<=3000,'全站静态文案预算');
 for(const [key,r] of Object.entries(results)){
 assert.equal(r.long.length,0,key+' 长句: '+r.long.join(' / '));
 if(budgets[key])assert.ok(r.chars<=budgets[key],key+' 超预算 '+r.chars);
 // Stronger than first viewport: all static explanatory text across the whole page.
 const cap=EXPLAIN_CAP[key]||120;
 assert.ok(r.explanationChars<=cap,key+' 常驻说明超过'+cap+'字');
 }
 const help=fs.readFileSync(path.join(root,'web/components.js'),'utf8');
 for(const k of ['仅提示','不计分','结果未知','估计值','未校验','球检测观测率','不是'])assert.ok(help.includes(k),k+' 口径丢失');
 assert.ok(help.includes('trigger="click"'));assert.ok(help.includes('type="button"'));
 const app=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
 for(const key of ['copy-note','page-help'])assert.ok(app.includes("app.component('"+key+"'"),'帮助组件必须注册');
 assert.equal(scan('<p>常驻</p><copy-note label="说明">隐藏说明内容</copy-note>').chars,4);
 assert.equal(scan('<p title="a > b">不能漏算</p>').chars,4);
 const c={window:{},console};vm.createContext(c);vm.runInContext(help,c);
 vm.runInContext(fs.readFileSync(path.join(root,'web/vendor/vue.global.prod.js'),'utf8'),c);
 const templates=[...Object.values(load()),...Object.values(c.window.COMPONENTS)];
 for(const x of templates)if(x.template)c.Vue.compile(x.template,{decodeEntities:s=>s.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>'),onError:e=>{throw e;}});

 const index=fs.readFileSync(path.join(root,'web/index.html'),'utf8');assert.equal((index.match(/<page-help\b/g)||[]).length,1);
 console.log('UI copy budget passed');
 }
}
module.exports={scan,results};
