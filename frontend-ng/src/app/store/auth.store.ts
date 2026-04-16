import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';

interface AuthState {
  userId: string | null;
  email: string | null;
  role: string | null;
  isAuthenticated: boolean;
}

const initialState: AuthState = {
  userId: null,
  email: null,
  role: null,
  isAuthenticated: false,
};

export const AuthStore = signalStore(
  { providedIn: 'root' },
  withState(initialState),
  withMethods((store) => ({
    setAuthenticated(user: { userId: string; email: string | null; role: string }) {
      patchState(store, {
        userId: user.userId,
        email: user.email,
        role: user.role,
        isAuthenticated: true,
      });
    },
    clear() {
      patchState(store, initialState);
    },
  }))
);
