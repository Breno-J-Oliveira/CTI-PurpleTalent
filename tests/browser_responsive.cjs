'use strict';
// Requires tests/serve_responsive.py: synthetic fixture, never a team database.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:5058';
const output = path.resolve('output/qa/responsive');
const label = process.env.RESPONSIVE_LABEL || 'after';
const widths = (process.env.RESPONSIVE_WIDTHS || '320,375,390,768,1024,1440').split(',').map(Number);
const themes = (process.env.RESPONSIVE_THEMES || 'dark,light').split(',');
const fixture = JSON.parse(fs.readFileSync(path.join(output, 'fixture.json'), 'utf8'));
const results = [], checks = [], errors = [], assets = [];
let browser;
function filename(value) { return value.replace(/[^a-z0-9_-]/gi, '_'); }
async function login(page, mentor) {
  await page.goto(base + '/login');
  await page.locator('[name=email]').fill(mentor ? 'mentor@cti.local' : 'candidato@demo.invalid');
  await page.locator('[name=password]').fill(mentor ? 'mentor123' : 'demonstracao123');
  await page.getByRole('button', { name: 'Entrar na plataforma', exact: true }).click();
  await page.waitForURL(url => !url.pathname.startsWith('/login'));
}
async function measure(page) {
  return page.evaluate(() => {
    const visible = el => {
      const style = getComputedStyle(el), r = el.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && r.width > 0 && r.height > 0;
    };
    const selector = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + [...el.classList].slice(0, 3).map(c => '.' + c).join('');
    const failures = [], clipped = [];
    for (const el of document.querySelectorAll('header *, .workspace-bar *, main *, footer *')) {
      if (!visible(el) || el.matches('svg *, option, .sr-only, input[type=hidden]')) continue;
      const r = el.getBoundingClientRect();
      if (r.left >= -1 && r.right <= innerWidth + 1) continue;
      let scrollable = false;
      for (let parent = el.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
        const s = getComputedStyle(parent);
        if (['auto','scroll'].includes(s.overflowX) && parent.scrollWidth > parent.clientWidth + 1) { scrollable = true; break; }
      }
      if (scrollable) continue;
      failures.push({ element: selector(el), left: Math.round(r.left), right: Math.round(r.right), text: (el.innerText || '').slice(0, 90) });
    }
    for (const el of document.querySelectorAll('main h1, main h2, main h3, main p, main label, main summary, main a, main button')) {
      if (!visible(el)) continue;
      const r=el.getBoundingClientRect();
      let intentional=false;
      for(let parent=el;parent && parent!==document.body;parent=parent.parentElement) {
        const s=getComputedStyle(parent);
        if(s.textOverflow==='ellipsis' || ['auto','scroll'].includes(s.overflowX)){intentional=true;break;}
        if(['hidden','clip'].includes(s.overflowX)) {
          const b=parent.getBoundingClientRect();
          if(r.left < b.left-2 || r.right > b.right+2) {
            clipped.push({element:selector(el),ancestor:selector(parent),text:(el.innerText||'').slice(0,90)});break;
          }
        }
      }
      if(intentional) continue;
    }
    const headerOverlap = [];
    const controls = [...document.querySelectorAll('.header-inner > *, .header-actions > *')].filter(visible);
    for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i], b = controls[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
      if (Math.min(ar.right,br.right)-Math.max(ar.left,br.left) > 1 && Math.min(ar.bottom,br.bottom)-Math.max(ar.top,br.top) > 1) headerOverlap.push([selector(a),selector(b)]);
    }
    return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
      outside: failures.slice(0, 15), clipped:clipped.slice(0,10), headerOverlap };
  });
}
(async () => {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const contexts = {}, pages = {};
  for (const role of ['guest','candidate','mentor']) {
    contexts[role] = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    pages[role] = await contexts[role].newPage();
    pages[role].on('pageerror', e => errors.push({ role, message: e.message }));
    pages[role].on('response', r => { if (r.status() >= 400 && r.url().includes('/static/')) assets.push(r.url()); });
  }
  await login(pages.candidate, false); await login(pages.mentor, true);
  const firstJob = fixture.jobs[0], draftJob = fixture.jobs[1], aid = fixture.applications[0];
  const routes = [
    ...['/','/login','/register','/opportunities',`/opportunities/${firstJob}`,'/blog','/purple-team'].map(route => ({ role:'guest',route })),
    ...['/my-applications',`/applications/${draftJob}/form`,`/applications/${draftJob}/review`,
      `/my-applications/${aid}/receipt`,`/my-applications/${aid}/assessment`,
      `/my-applications/${fixture.pendingApplication}/assessment`,`/remote-lab/${fixture.instance}`,`/challenge/${fixture.incident}/lab-status`,
      '/challenges','/labs','/ranking','/profile','/progress','/teams',
      ...fixture.challenges.map(id => `/challenge/${id}`)].map(route => ({role:'candidate',route})),
    ...['/admin','/dashboard','/jobs','/admin/jobs/new',`/admin/jobs/${firstJob}/edit`,
      `/admin/jobs/${firstJob}/preview`,`/admin/jobs/${firstJob}/form`,`/admin/applications/${aid}`,
      `/participante/${fixture.user}`,'/ambientes','/teams','/admin/occurrences','/admin/blog',
      `/admin/blog/${fixture.post}`,'/admin/challenges',`/admin/challenges/${fixture.challenges[0]}`].map(route => ({role:'mentor',route})),
    {role:'guest',route:'/pagina-qa-inexistente',status:404},
    {role:'candidate',route:'/admin',status:403},
    {role:'guest',route:'/logout',status:405},
  ];
  const unmatched = fixture.htmlRoutes.filter(route => !routes.some(test => {
    const regexp = '^' + route.replace(/<int:\w+>/g, '\\d+') + '$';
    return new RegExp(regexp).test(test.route);
  }));
  for (const width of process.env.RESPONSIVE_INTERACTIONS_ONLY ? [] : widths) {
    for (const theme of themes) {
      for (const test of routes) {
        const page = pages[test.role];
        await page.setViewportSize({width,height:1000});
        const response = await page.goto(base + test.route);
        await page.evaluate(theme => { document.documentElement.dataset.theme = theme; localStorage.setItem('pt-theme', theme); }, theme);
        await page.evaluate(() => document.fonts.ready);
        if(test.route==='/') await page.getByRole('heading',{name:'Contrate talentos pelo que eles sabem fazer',exact:true}).waitFor();
        const data = await measure(page);
        const status = response.status();
        const expected = test.status || 200;
        const failed = data.overflow || data.outside.length > 0 || data.clipped.length > 0 || data.headerOverlap.length > 0 || status !== expected;
        const result = {...test,width,theme,status,failed,...data};
        results.push(result);
        if (failed || (width === 375 && theme === 'dark' && ['/', '/admin', '/teams','/admin/challenges', '/labs','/profile','/jobs'].includes(test.route))) {
          const file = `${label}-${test.role}-${filename(test.route)}-${width}-${theme}.png`;
          // Load lazy previews and let the actual IntersectionObserver reveal
          // sections before screenshots; do not fake their CSS visibility.
          for(const el of await page.locator('.reveal').all()) await el.scrollIntoViewIfNeeded();
          for(const el of await page.locator('img[loading=lazy]').all()) await el.scrollIntoViewIfNeeded();
          await page.evaluate(async()=>{await Promise.all([...document.images].map(img=>img.decode().catch(()=>{})));window.scrollTo(0,0);});
          await page.screenshot({path:path.join(output,file),fullPage:true});
          result.screenshot=file;
        }
        if (failed) console.log(JSON.stringify({role:test.role,route:test.route,width,theme,status,documentWidth:data.documentWidth,outside:data.outside.slice(0,3),clipped:data.clipped,headerOverlap:data.headerOverlap}));
        const details=page.locator('main details');
        if(await details.count()) {
          await details.evaluateAll(els=>els.forEach(el=>el.open=true));
          const expanded=await measure(page);
          const bad=expanded.overflow||expanded.outside.length>0||expanded.clipped.length>0||expanded.headerOverlap.length>0;
          const entry={...test,route:test.route+'#expanded-details',width,theme,status,failed:bad,...expanded};
          results.push(entry);
          if(bad) {entry.screenshot=`${label}-${test.role}-${filename(test.route)}-expanded-${width}-${theme}.png`;await page.screenshot({path:path.join(output,entry.screenshot),fullPage:true});console.log(JSON.stringify(entry));}
        }
      }
    }
    console.log(`Checked ${width}px: ${results.filter(r=>r.width===width).length} page/theme cases`);
    fs.writeFileSync(path.join(output,`${label}-results.json`),JSON.stringify({results,errors,assets,unmatched},null,2));
  }
  // Check expanded menus and focus restoration separately: hidden menus have no layout.
  for (const role of ['guest','candidate','mentor']) for (const width of [320,375,768,1024]) {
    const page=pages[role]; await page.setViewportSize({width,height:700}); await page.goto(base+'/');
    const button=page.locator('.nav-toggle');
    if(await button.isVisible()) {
      await button.focus(); await page.keyboard.press('Enter');
      assert.equal(await button.getAttribute('aria-expanded'),'true');
      const data=await measure(page);
      results.push({role,route:'/#expanded-menu',width,theme:await page.locator('html').getAttribute('data-theme'),failed:data.overflow||data.outside.length>0||data.clipped.length>0||data.headerOverlap.length>0,...data});
      await page.screenshot({path:path.join(output,`${label}-${role}-menu-${width}.png`),fullPage:true});
      await page.keyboard.press('Escape');
      assert.equal(await button.getAttribute('aria-expanded'),'false');
      assert.equal(await button.evaluate(el=>el===document.activeElement),true);
    }
  }
  async function verify(name, fn) {
    try {await fn();checks.push({name,status:'passed'});}
    catch(error){checks.push({name,status:'failed',error:error.message});throw error;}
    finally {fs.writeFileSync(path.join(output,`${label}-results.json`),JSON.stringify({results,checks,errors,assets,unmatched},null,2));}
  }
  await verify('Landscape menus: expanded links remain reachable and Escape restores focus',async()=>{
    for(const role of ['guest','candidate','mentor']) for(const size of [{width:844,height:390},{width:768,height:360}]) {
      const page=pages[role];await page.setViewportSize(size);await page.goto(base+'/');
      const menu=page.locator('.nav-toggle');await menu.click();
      if(role!=='mentor')await page.locator('.learn-menu summary').click();
      const link=role==='mentor'?page.locator('#site-navigation a').last():page.locator('.learn-menu').getByRole('link',{name:'Ranking',exact:true});
      await link.scrollIntoViewIfNeeded();const r=await link.boundingBox();
      assert.ok(r.y>=-1 && r.y+r.height<=size.height+1,`${role} ${size.width}x${size.height}: link outside viewport (${r.y}..${r.y+r.height})`);
      await page.screenshot({path:path.join(output,`${label}-${role}-landscape-${size.width}.png`)});
      await page.keyboard.press('Escape');assert.equal(await menu.getAttribute('aria-expanded'),'false');assert.equal(await menu.evaluate(el=>el===document.activeElement),true);
      await menu.click();if(role!=='mentor')await page.locator('.learn-menu summary').click();
      await link.click();await page.waitForURL(url=>role==='guest'?url.pathname==='/login':role==='candidate'?url.pathname==='/ranking':url.pathname==='/admin/challenges');
    }
  });
  await verify('Mobile search, password visibility, and persisted theme work',async()=>{
    const p=pages.guest;await p.setViewportSize({width:375,height:812});await p.goto(base+'/login');
    const password=p.locator('[name=password]');await password.fill('senha-ficticia-sem-envio');
    await p.getByRole('button',{name:'Mostrar senha',exact:true}).click();assert.equal(await password.getAttribute('type'),'text');
    await p.getByRole('button',{name:'Ocultar senha',exact:true}).click();assert.equal(await password.getAttribute('type'),'password');
    const previous=await p.locator('html').getAttribute('data-theme');await p.locator('[data-theme-toggle]').click();await p.reload();
    assert.notEqual(await p.locator('html').getAttribute('data-theme'),previous);
    await p.goto(base+'/opportunities');await p.locator('[name=q]').fill('não-existe-qa-responsividade');await p.getByRole('button',{name:'Encontrar vagas',exact:true}).click();
    await p.getByRole('heading',{name:'Nenhuma vaga corresponde aos filtros',exact:true}).waitFor();
    await p.getByRole('link',{name:'Ver todas as vagas',exact:true}).click();assert.ok(await p.locator('.opportunity-card').count()>0);
    const cp=pages.candidate;await cp.setViewportSize({width:320,height:812});await cp.goto(base+'/challenges');
    const search=cp.locator('[data-filter]');await search.fill('nenhum-desafio-qa');assert.equal(await cp.locator('.ctf-row:visible').count(),0);
    await search.fill('Boas-vindas');assert.equal(await cp.locator('.ctf-row:visible').count(),1);
    await search.fill('');assert.ok(await cp.locator('.ctf-row:visible').count()>1);
  });
  await verify('Question editor reorders and previews on mobile without saving',async()=>{
    const p=pages.mentor;await p.setViewportSize({width:320,height:812});await p.goto(base+`/admin/jobs/${firstJob}/form`);
    const rows=p.locator('[data-question-list] > [data-question-row]');const first=await rows.nth(0).locator('[data-question-label]').inputValue();
    await rows.nth(0).locator('[data-question-down]').click();assert.equal(await rows.nth(1).locator('[data-question-label]').inputValue(),first);
    await rows.nth(1).locator('[data-question-up]').click();assert.equal(await rows.nth(0).locator('[data-question-label]').inputValue(),first);
    await rows.nth(0).locator('[data-question-label]').fill('Pergunta sintética de QA para verificar a prévia no celular');
    await p.locator('.question-preview summary').click();await p.locator('[data-question-preview]').getByText('Pergunta sintética de QA para verificar a prévia no celular',{exact:false}).first().waitFor();
    const data=await measure(p);assert.equal(data.overflow,false);assert.deepEqual(data.outside,[]);assert.deepEqual(data.clipped,[]);
    await p.screenshot({path:path.join(output,`${label}-editor-preview-320.png`),fullPage:true});
    // No save is sent. Reload proves only local preview/order state changed.
    await p.reload();assert.equal(await rows.nth(0).locator('[data-question-label]').inputValue(),first);
  });
  await verify('Mobile navigation and login remain usable without JavaScript',async()=>{
    const plain=await browser.newContext({javaScriptEnabled:false,viewport:{width:375,height:812}});
    const page=await plain.newPage();await page.goto(base+'/login');assert.ok(await page.locator('#site-navigation').isVisible());
    assert.ok(await page.locator('#site-navigation a[href="/register"]').isVisible());
    assert.equal(await page.locator('[data-password-toggle]').isVisible(),false);
    assert.ok(await page.locator('[name=password]').isVisible());assert.equal((await measure(page)).overflow,false);await plain.close();
  });
  await verify('Dossier link and editor field help do not overlap adjacent content',async()=>{
    const p=pages.mentor;
    for(const width of [320,375,768]) for(const theme of ['dark','light']) {
      await p.setViewportSize({width,height:900});await p.goto(base+`/admin/applications/${aid}`);
      await p.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      const gaps=await p.locator('.review-dossier a + .field-help').evaluateAll(els=>els.map(el=>el.getBoundingClientRect().top-el.previousElementSibling.getBoundingClientRect().bottom));
      assert.ok(gaps.length>0);assert.ok(gaps.every(gap=>gap>=7.5),`Dossier ${width} ${theme}: gaps=${gaps}`);
      for(const route of ['/admin/blog',`/admin/blog/${fixture.post}`,'/admin/challenges',`/admin/challenges/${fixture.challenges[0]}`]) {
        await p.goto(base+route);await p.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
        const bad=await p.locator('.blog-admin .field-help,.blog-edit .field-help').evaluateAll(els=>els.map(el=>{
          let prev=el.previousElementSibling;
          while(prev && !prev.getBoundingClientRect().height)prev=prev.previousElementSibling;
          if(!prev)return null;
          return {text:el.textContent.slice(0,40),gap:el.getBoundingClientRect().top-prev.getBoundingClientRect().bottom};
        }).filter(row=>row && row.gap<7.5));
        assert.deepEqual(bad,[],`${route} ${width} ${theme}: helper overlaps previous control`);
      }
    }
  });
  await verify('Every challenge briefing is checked unlocked through the mentor account',async()=>{
    const p=pages.mentor;
    for(const width of [320,768,1440]) for(const theme of ['dark','light']) for(const cid of fixture.challenges) {
      await p.setViewportSize({width,height:1000});const response=await p.goto(base+`/challenge/${cid}`);
      await p.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);await p.evaluate(()=>document.fonts.ready);
      assert.equal(response.status(),200);assert.equal(await p.locator('.team-lock').count(),0);
      assert.ok((await p.locator('.challenge-briefing .pre').textContent()).trim().length>0);
      const data=await measure(p);
      assert.equal(data.overflow,false,`Unlocked briefing ${cid} ${width} ${theme}`);assert.deepEqual(data.outside,[]);assert.deepEqual(data.clipped,[]);
    }
  });
  fs.writeFileSync(path.join(output,`${label}-results.json`),JSON.stringify({results,checks,errors,assets,unmatched},null,2));
  const failures=results.filter(r=>r.failed);
  console.log(JSON.stringify({cases:results.length,failures:failures.length,checks,errors,assets,unmatched},null,2));
  assert.deepEqual(unmatched,[], 'Every HTML GET route must have a responsive case.');
  if(failures.length || errors.length || assets.length) process.exitCode=1;
})().catch(error=>{console.error(error.stack);process.exitCode=1;})
  .finally(async()=>{if(browser)await browser.close();});
