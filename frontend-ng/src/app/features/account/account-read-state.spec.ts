import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DestroyRef, Injector } from '@angular/core';
import { Router } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { AuthApiService } from '@app/core/auth-api.service';
import { I18nService } from '@app/core/i18n.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';
import { SecurityComponent } from './security.component';
import { SessionsComponent } from './sessions.component';
import { PasswordResetComponent } from '../auth/password-reset.component';

function create<T>(component: new (...args: any[]) => T, api: object) {
  const injector = Injector.create({ providers: [
    component,
    { provide: AuthApiService, useValue: api },
    { provide: I18nService, useValue: { t: (key: string) => key } },
    { provide: ToastrService, useValue: { error() {}, success() {} } },
    { provide: TokenStorageService, useValue: { clear() {} } },
    { provide: AuthStore, useValue: { clear() {} } },
    { provide: Router, useValue: { navigate() {} } },
    { provide: DestroyRef, useValue: { onDestroy: () => () => undefined } },
  ] });
  return injector.get(component);
}

for (const status of [0, 403, 500, 504]) {
  test(`MFA read ${status} leaves no actionable disabled default`, () => {
    let writes = 0;
    const component = create(SecurityComponent, {
      me: () => throwError(() => ({ status })),
      toggleMfa: () => { writes++; return of({ mfa_enabled: true }); },
    });
    assert.equal(component.readState().s, status === 403 ? 'denied' : 'error');
    component.toggle();
    assert.equal(writes, 0);
  });

  test(`session read ${status} is not an empty successful list`, () => {
    const component = create(SessionsComponent, { listSessions: () => throwError(() => ({ status })) });
    assert.equal(component.readState().s, status === 403 ? 'denied' : 'error');
  });
}

test('an authoritative disabled MFA status becomes actionable and retry recovers', () => {
  let failed = true;
  let writes = 0;
  const component = create(SecurityComponent, {
    me: () => failed ? throwError(() => ({ status: 500 })) : of({ mfa_enabled: false }),
    toggleMfa: () => { writes++; return of({ mfa_enabled: true }); },
  });
  failed = false;
  component.load();
  assert.equal(component.readState().s, 'ready');
  component.toggle();
  assert.equal(writes, 1);
  assert.equal(component.enabled(), true);
});

test('successful empty sessions remain empty', () => {
  const component = create(SessionsComponent, { listSessions: () => of([]) });
  assert.equal(component.readState().s, 'empty');
});

test('password recovery only announces neutral success after server confirmation', () => {
  let request = new Subject<unknown>();
  const component = create(PasswordResetComponent, { passwordReset: () => request });
  component.email = 'reader@example.test';
  component.onSubmit();
  assert.equal(component.loading(), true);
  assert.equal(component.sent(), false);
  request.error({ status: 502 });
  assert.equal(component.sent(), false);
  assert.equal(component.failure()?.s, 'error');
  request = new Subject<unknown>();
  component.onSubmit();
  request.next({ status: 'ok' });
  assert.equal(component.sent(), true);
  assert.equal(component.failure(), null);
});
