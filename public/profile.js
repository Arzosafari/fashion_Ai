(() => {
  // All list inputs accept user-defined values, one per line. Styles also offer
  // checkboxes for common choices; unknown saved values are retained below them.
  const sections = [
    ['personal','Personal information','The basics you choose to share.', [
      ['display_name','Display name'], ['age_range','Age range'], ['gender_presentation','Gender presentation'], ['country','Country'], ['city','City'], ['preferred_language','Preferred language'], ['units','Units','select',['metric','imperial']]]],
    ['style','Style preferences','The colors, looks and ideas you gravitate toward.', [
      ['preferred_styles','Preferred styles','styles',['casual','smart casual','minimalist','classic','streetwear','formal','sporty','romantic','bohemian','edgy','elegant']],
      ['preferred_colors','Preferred colors','list'], ['avoided_colors','Colors to avoid','list'], ['preferred_patterns','Preferred patterns','list'], ['fashion_goals','Fashion goals','list'], ['trend_interest','Interest in trends','select',['low','medium','high']], ['style_experimentation','Style experimentation','select',['conservative','balanced','experimental']], ['style_inspiration','Style inspiration','note']]],
    ['sizes','Clothing sizes & fit','Optional sizing information; labels can vary by brand.', [
      ['fit_preference','Fit preference','select',['slim','regular','relaxed','oversized']], ['top_size','Top size'], ['bottom_size','Bottom size'], ['dress_size','Dress size'], ['shoe_size','Shoe size'], ['shoe_size_system','Shoe size system','select',['EU','US','UK']], ['size_notes','Size notes','note']]],
    ['shopping','Budget & shopping','A guide to how you like to shop.', [
      ['budget_level','Budget level','select',['budget-conscious','moderate','premium','luxury']], ['shopping_priorities','Shopping priorities','list'], ['preferred_brands','Preferred brands','list'], ['avoided_brands','Brands to avoid','list']]],
    ['lifestyle','Lifestyle & occasions','Tell us what you dress for most often.', [
      ['common_occasions','Common occasions','list'], ['climate_comfort','Climate comfort','select',['hot','mild','cold']], ['comfort_priorities','Comfort priorities','list'], ['lifestyle_notes','Lifestyle notes','note']]],
    ['restrictions','Restrictions & additional preferences','Practical needs and things you prefer to avoid.', [
      ['avoided_materials','Materials to avoid','list'], ['clothing_restrictions','Clothing restrictions','list'], ['coverage_preference','Coverage preference'], ['accessibility_preferences','Accessibility preferences','list'], ['additional_notes','Additional notes','note']]]
  ];
  const form = document.getElementById('profileForm'), notice = document.getElementById('profileNotice');
  const save = document.getElementById('saveProfile'), cancel = document.getElementById('cancelProfile');
  let saved = null, baseline = '', dirty = false, busy = false;
  const title = v => v.charAt(0).toUpperCase() + v.slice(1);
  const escape = s => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const container = document.getElementById('profileSections');
  container.innerHTML = sections.map(([group, heading, desc, fields], i) => `
    <section class="profile-section" aria-labelledby="heading-${group}">
      <div><span class="profile-number">${String(i+1).padStart(2,'0')} / 06</span><h3 id="heading-${group}">${heading}</h3><p>${desc}</p></div>
      <div class="profile-fields">${fields.map(([key,label,type,options]) => {
        const id = `${group}-${key}`;
        if (type === 'styles') return `<div class="profile-field wide"><fieldset><legend>${label}</legend><div class="profile-checks">${options.map(v=>`<label><input type="checkbox" name="style-choice" value="${escape(v)}">${escape(title(v))}</label>`).join('')}</div><label for="${id}">Other styles</label><textarea id="${id}" rows="2" placeholder="Add your own, one per line"></textarea><small>Choose any styles or add your own below.</small></fieldset></div>`;
        let control;
        if(type === 'select') control = `<select id="${id}"><option value="">Not specified</option>${options.map(v=>`<option value="${escape(v)}">${escape(title(v))}</option>`).join('')}</select>`;
        else if(type === 'list' || type === 'note') control = `<textarea id="${id}" rows="2" ${type === 'note' ? 'maxlength="2000"' : ''} placeholder="${type === 'list' ? 'One per line' : 'Optional'}"></textarea>`;
        else control = `<input id="${id}" type="text" maxlength="100" placeholder="Optional">`;
        return `<div class="profile-field ${type === 'note' ? 'wide' : ''}"><label for="${id}">${label}</label>${control}${type === 'list' ? '<small>One per line, up to 30.</small>' : ''}</div>`;
      }).join('')}</div></section>`).join('');
  function show(message, error=false) { notice.textContent=message; notice.classList.toggle('error',error); }
  function values() {
    const data = {};
    sections.forEach(([group,,,fields])=>{
      data[group]={};
      fields.forEach(([key,,type])=>{
        const raw=document.getElementById(`${group}-${key}`).value.trim();
        if(type==='list' || type==='styles') {
          let list=raw ? raw.split(/\r?\n/).map(s=>s.trim()).filter(Boolean) : [];
          if(type==='styles') list=[...document.querySelectorAll('input[name="style-choice"]:checked')].map(el=>el.value).concat(list);
          data[group][key]=[...new Set(list)];
        } else data[group][key]=raw || null;
      });
    });
    return data;
  }
  function fill(data) {
    sections.forEach(([group,,,fields])=>fields.forEach(([key,,type,options])=>{
      const value=data?.[group]?.[key];
      const el=document.getElementById(`${group}-${key}`);
      if(type==='styles') {
        const styles=value || [];
        document.querySelectorAll('input[name="style-choice"]').forEach(c=>c.checked=styles.includes(c.value));
        el.value=styles.filter(v=>!options.includes(v)).join('\n');
      } else el.value=type==='list' ? (value || []).join('\n') : (value ?? '');
    }));
    baseline=JSON.stringify(values()); dirty=false;
  }
  function checkDirty() { dirty=JSON.stringify(values())!==baseline; }
  form.addEventListener('input',checkDirty); form.addEventListener('change',checkDirty);
  window.addEventListener('beforeunload', e=>{ if(dirty) { e.preventDefault(); e.returnValue=''; } });
  cancel.addEventListener('click',()=>{ if(dirty && !confirm('Discard your unsaved changes?')) return; fill(saved); show(saved ? 'Changes discarded. Your saved profile is unchanged.' : 'No profile yet. Add any preferences and save to get started.'); });
  async function errorMessage(res) {
    const body=await res.json().catch(()=>({}));
    if(Array.isArray(body.detail)) return body.detail.map(e=>`${e.loc.slice(1).join(' › ')}: ${e.msg}`).join('; ');
    return body.detail || `Request failed (${res.status}).`;
  }
  form.addEventListener('submit',async e=>{
    e.preventDefault(); if(busy) return;
    const data=values();
    for(const [group, fields] of Object.entries(data)) for(const [key,v] of Object.entries(fields)) {
      if(Array.isArray(v) && (v.length>30 || v.some(s=>s.length>100))) { show(`${key.replaceAll('_',' ')}: use at most 30 entries, each up to 100 characters.`,true); document.getElementById(`${group}-${key}`).focus(); return; }
    }
    busy=true; save.disabled=true; cancel.disabled=true; container.querySelectorAll('input,select,textarea').forEach(el=>el.disabled=true); show('Saving changes…');
    try {
      const res=await fetch('/api/v1/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      if(!res.ok) throw new Error(await errorMessage(res));
      saved=await res.json(); fill(saved); show('Profile saved. Your preferences will be used on your next request.');
    } catch(err) { show(`Could not save your profile: ${err.message}`,true); }
    finally { busy=false; save.disabled=false; cancel.disabled=false; container.querySelectorAll('input,select,textarea').forEach(el=>el.disabled=false); }
  });
  async function load() {
    try {
      const res=await fetch('/api/v1/profile');
      if(res.status===404) { saved=null; fill(null); form.hidden=false; show('No profile yet. Add any preferences and save to get started.'); return; }
      if(!res.ok) throw new Error(await errorMessage(res));
      saved=await res.json(); fill(saved); form.hidden=false; show('Your saved preferences are ready to edit.');
    } catch(err) { show(`Could not load your profile: ${err.message}`,true); }
  }
  load();
})();
