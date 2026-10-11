import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';

export interface WorkspaceEntry {
  id: string;
  name: string;
  slug: string;
  role: string;
}

interface WorkspaceState {
  workspaces: WorkspaceEntry[];
  currentSlug: string | null;
}

const initialState: WorkspaceState = {
  workspaces: [],
  currentSlug: null,
};

export const WorkspaceStore = signalStore(
  { providedIn: 'root' },
  withState(initialState),
  withMethods((store) => ({
    setWorkspaces(workspaces: WorkspaceEntry[]) {
      patchState(store, { workspaces });
    },
    setCurrent(slug: string) {
      patchState(store, { currentSlug: slug });
    },
    clear() {
      patchState(store, initialState);
    },
  }))
);
