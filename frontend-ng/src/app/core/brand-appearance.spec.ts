import assert from 'node:assert/strict';
import test from 'node:test';
import { appearanceLogo, appearanceStyles, brandAppearance, brandLogo } from './brand-appearance';

test('appearance accepts bounded options and never exposes arbitrary CSS or native profiles', () => {
  assert.deepEqual(brandAppearance({ palette:'nawa', accent:'url(evil)', corners:'900px', css:'body{}', logo:'javascript:evil()' }), {});
  assert.equal(brandLogo('//tracker.test/logo.png'), '');
  assert.equal(brandLogo('https://user:password@example.test/logo'), '');
  assert.equal(brandLogo('/assets/nawa/nawa-logo.png'), '/assets/nawa/nawa-logo.png');
  assert.equal(brandLogo('data:image/svg+xml;base64,AAAA'), '');
});

test('preview and runtime use the same palette, contrast choice and logo fallback', () => {
  const brand = {palette:'graphite', accent:'#ffffff', logo:'/logo.png', logo_light:'/light.png', corners:'square'};
  const dark = appearanceStyles(brand, 'dark');
  const light = appearanceStyles(brand, 'light');
  assert.equal(dark['--ck-bg-base'], '#090909');
  assert.equal(light['--ck-bg-base'], '#f4f4f4');
  assert.equal(dark['--ck-cta-fg'], '#05070a');
  assert.equal(dark['--ck-radius-md'], '0px');
  assert.equal(appearanceLogo(brand, 'light'), '/light.png');
  assert.equal(appearanceLogo({logo:'/logo.png'}, 'light'), '/logo.png');
  assert.equal(appearanceLogo(brand, 'dark'), '/logo.png');
  assert.equal(Object.keys(dark).some(key => /status|signal|mission|nawa/.test(key)), false);
  assert.deepEqual(appearanceStyles({}, 'dark'), {});
});


test('custom mid-tone accents keep readable text at the contrast boundary', () => {
  assert.equal(appearanceStyles({accent:'#707972'}, 'light')['--ck-cta-fg'], '#000000');
});
