# Runpod GPU Worker Orchestrator

A lightweight service that automatically spawns, monitors, and tears down Runpod GPU workers based on task demand tracked in Supabase.

## Quick Start

1. Follow the setup checklist in `user_checklist.md`
2. Copy `env.example` to `.env` and fill in your API keys
3. Install dependencies: `pip install -r requirements.txt`
4. Set up database schema: `python scripts/setup_database.py`
5. Run orchestrator: `python -m gpu_orchestrator.main single`

## Deployment

See `DEPLOYMENT_GUIDE.md` for comprehensive deployment options. **Recommended**: Simple cloud VM with cron scheduling.

- 🥇 **Most users**: VM + Cron (reliable, simple, ~$5-15/month)
- 🐳 **Containers**: Docker Compose, AWS ECS, Kubernetes, Google Cloud Run
- ❌ **Avoid**: Supabase Edge Functions (timeout and reliability issues)

## Project Structure

```
orchestrator/           # Main orchestrator logic
├── __init__.py
├── main.py            # Entry point
├── database.py        # Supabase helpers
├── runpod_client.py   # Runpod API wrapper
└── control_loop.py    # Core orchestration logic

# GPU workers run Headless-Wan2GP (separate repo)
# See: https://github.com/peteromallet/Headless-Wan2GP

scripts/               # CLI utilities
├── setup_database.py  # Database schema setup
├── test_supabase.py   # Connection tests
├── test_runpod.py     # Runpod API tests
└── spawn_gpu.py       # Manual GPU spawning

tests/                 # Test suite
└── test_*.py
```

## Documentation

- `orchestrator_plan.md` - Detailed implementation plan and architecture
- `user_checklist.md` - Setup prerequisites and testing steps

## Development

Run tests: `pytest`
Format code: `black . && isort .`
Type check: `mypy orchestrator/` 