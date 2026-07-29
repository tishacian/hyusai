import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';

interface AuthState {
  userId: string | null;
  email: string | null;
  role: string | null;
  isAuthenticated: boolean;
  /** Opaque process-local principal generation; never derived from a token. */
  authEpoch: number;
}

const initialState: AuthState = {
  userId: null,
  email: null,
  role: null,
  isAuthenticated: false,
  authEpoch: 0,
};

export interface AuthenticationRequestScope {
  readonly epoch: number;
}

export interface AuthenticationContextTransition {
  readonly previousEpoch: number;
  readonly nextEpoch: number;
}

type AuthenticationContextResetter = (
  transition: AuthenticationContextTransition,
) => void;

export class AuthenticationRequestInvalidatedError extends Error {
  override readonly name = 'AuthenticationRequestInvalidatedError';

  constructor() {
    super('Authenticated principal changed before the request completed.');
  }
}

export const AuthStore = signalStore(
  { providedIn: 'root' },
  withState(initialState),
  withMethods((store) => {
    const contextResetters = new Set<AuthenticationContextResetter>();

    const beginPrincipalTransition = (): AuthenticationContextTransition => {
      const previousEpoch = store.authEpoch();
      const transition = Object.freeze({
        previousEpoch,
        nextEpoch: previousEpoch + 1,
      });
      // Reset principal-derived root caches synchronously while the previous
      // epoch is still current. The following patch publishes identity and its
      // opaque generation atomically.
      for (const resetter of [...contextResetters]) {
        try {
          resetter(transition);
        } catch (error) {
          console.error('Authentication context reset failed', error);
        }
      }
      return transition;
    };

    return {
      setAuthenticated(user: { userId: string; email: string | null; role: string }) {
        const transition = beginPrincipalTransition();
        patchState(store, {
          userId: user.userId,
          email: user.email,
          role: user.role,
          isAuthenticated: true,
          authEpoch: transition.nextEpoch,
        });
      },
      clear() {
        const transition = beginPrincipalTransition();
        patchState(store, {
          userId: null,
          email: null,
          role: null,
          isAuthenticated: false,
          authEpoch: transition.nextEpoch,
        });
      },
      captureRequestScope(): AuthenticationRequestScope {
        return Object.freeze({ epoch: store.authEpoch() });
      },
      isRequestScopeCurrent(scope: AuthenticationRequestScope): boolean {
        return store.authEpoch() === scope.epoch;
      },
      registerContextReset(resetter: AuthenticationContextResetter): () => void {
        contextResetters.add(resetter);
        return () => contextResetters.delete(resetter);
      },
    };
  }),
);
