// Optional DOM interaction tests: see README for the jsdom setup command.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const html = fs.readFileSync('public/profile.html', 'utf8');
const script = fs.readFileSync('public/profile.js', 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function setup(fetch) {
  const dom = new JSDOM(html, {runScripts:'outside-only', url:'http://localhost/profile.html'});
  dom.window.fetch=fetch; dom.window.confirm=()=>true;
  dom.window.eval(script);
  return dom;
}
const result = (status, body) => ({status, ok:status>=200&&status<300, json:async()=>body});
test('empty profile, save, cancel, reload saved values and validation', async () => {
  let stored = null, writes=0;
  const fetch = async (url, opts) => {
    if(opts?.method==='PUT') { writes++; stored=JSON.parse(opts.body); return result(200, stored); }
    return stored ? result(200,stored) : result(404,{});
  };
  const dom=setup(fetch); await tick();
  const d=dom.window.document;
  assert.match(d.getElementById('profileNotice').textContent,/No profile yet/);
  assert.equal(d.getElementById('profileForm').hidden,false);
  const name=d.getElementById('personal-display_name'); name.value='Ada'; name.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  d.getElementById('profileForm').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})); await tick();
  assert.equal(stored.personal.display_name,'Ada'); assert.match(d.getElementById('profileNotice').textContent,/Profile saved/);
  name.value='Changed'; name.dispatchEvent(new dom.window.Event('input',{bubbles:true})); d.getElementById('cancelProfile').click(); assert.equal(name.value,'Ada');
  const colors=d.getElementById('style-preferred_colors'); colors.value=Array.from({length:31},(_,i)=>`color ${i}`).join('\n');
  d.getElementById('profileForm').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})); await tick();
  assert.equal(writes,1); assert.match(d.getElementById('profileNotice').textContent,/at most 30/);
  const dom2=setup(fetch); await tick(); assert.equal(dom2.window.document.getElementById('personal-display_name').value,'Ada');
});
test('loading, API failure and save failure are visible', async () => {
  let resolve;
  const dom=setup(()=>new Promise(r=>resolve=r));
  const d=dom.window.document; assert.match(d.getElementById('profileNotice').textContent,/Loading/); assert.equal(d.getElementById('profileForm').hidden,true);
  resolve(result(503,{detail:'Disabled'})); await tick(); assert.match(d.getElementById('profileNotice').textContent,/Disabled/);
  let count=0;
  const dom2=setup(async()=> ++count===1 ? result(404,{}) : result(500,{detail:'Storage offline'})); await tick();
  const d2=dom2.window.document; d2.getElementById('profileForm').dispatchEvent(new dom2.window.Event('submit',{bubbles:true,cancelable:true})); await tick();
  assert.match(d2.getElementById('profileNotice').textContent,/Storage offline/); assert.equal(d2.getElementById('saveProfile').disabled,false);
});
