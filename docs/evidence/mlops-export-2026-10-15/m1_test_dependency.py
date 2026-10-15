# Qualify the real M1 policy from its sibling worktree, without copying source.
import app.services
app.services.__path__.append('/workspace/hyusai-mlops-m1/backend/app/services')
