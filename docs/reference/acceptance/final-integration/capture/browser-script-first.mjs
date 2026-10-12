import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const evidence = process.env.HH_BROWSER_EVIDENCE;
const inputs = JSON.parse(fs.readFileSync(evidence + '/browser-inputs.json'));
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1280,height:900}});
  const errors = [], failures = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => {if(r.status()>=400) failures.push({path:new URL(r.url()).pathname,status:r.status()});});
  await page.goto(inputs.url);
  assert.equal(await page.title(), 'Harbor Helper · 团队实验室');
  await page.getByLabel('账户').fill('fixture-member');
  await page.getByLabel('密码', {exact:true}).fill('Fixture-only-member-password-2026');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  const accepted=[];
  for(const [index, version] of ['', ...inputs.versions].entries()) {
    await page.getByRole('link',{name:'新建实验',exact:true}).click();
    await page.getByLabel('数据集',{exact:true}).selectOption(inputs.dataset_id);
    await page.getByLabel('执行方案',{exact:true}).selectOption('oracle');
    await page.getByLabel('团队附件版本（可选）').selectOption(version);
    if(!version) await page.getByRole('button',{name:'清除附件，使用无附件基线'}).click();
    await page.locator('details summary').click();
    await page.locator('[name=attempts]').fill('1');
    await page.locator('[name=concurrency]').fill('1');
    await page.locator('[name=wall_seconds]').fill('120');
    const response=page.waitForResponse(r=>r.url().endsWith('/api/v1/submissions')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'提交实验',exact:true}).click();
    const r=await response; assert.equal(r.status(),202);
    const value=await r.json();
    assert.equal(value.attachment.attachment_version_id,version||null);
    accepted.push(value);
    await page.waitForURL(/\/submissions\/sub-/);
    await page.screenshot({path:evidence+`/browser-submit-${index}.png`,fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('link',{name:'共享实验',exact:true}).click();
  await page.getByRole('heading',{name:'共享实验',exact:true}).waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  assert.equal(await page.locator('vite-error-overlay').count(),0);
  assert.deepEqual(errors,[]);
  assert.deepEqual(failures,[{path:'/api/v1/me',status:401}]);
  await page.screenshot({path:evidence+'/browser-shared-mobile.png',fullPage:true});
  fs.writeFileSync(evidence+'/browser-submissions.json',JSON.stringify(accepted,null,2));
  console.log('production browser: login -> actual no-attachment/v1/v2 submit -> shared mobile list; identity/content/overlay/interaction/pageerror checks passed; expected initial anonymous 401 only');
} finally {await browser.close();}
