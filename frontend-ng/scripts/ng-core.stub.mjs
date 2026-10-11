/**
 * Minimal `@angular/core` stub used ONLY by the unit-test bundler
 * (`scripts/run-unit.mjs`). The engine-agnostic units under test
 * (`FlowSerializerService`) use `@angular/core` purely for the `@Injectable`
 * decorator, which is metadata-only and irrelevant to the pure logic we test.
 * Aliasing it here keeps the unit tests free of the full Angular runtime.
 */
export const Injectable = () => (target) => target;
export const Component = () => (target) => target;
export const inject = () => {
  throw new Error('inject() is not available in the unit-test stub');
};
