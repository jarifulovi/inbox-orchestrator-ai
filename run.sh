#!/bin/bash

# run.sh - Helper script to run InboxOrchestratorAI app or workers.
# Automatically uses the local virtual environment (.venv) python path.

# Set PYTHONPATH to the current directory so imports work correctly
export PYTHONPATH=$(pwd)

# Default options
SKIP_ML_VAL="False"
COMMAND=""

# Parse arguments
for arg in "$@"
do
    case $arg in
        app)
        COMMAND="app"
        shift
        ;;
        worker)
        COMMAND="worker"
        shift
        ;;
        --skip-ml)
        SKIP_ML_VAL="True"
        shift
        ;;
        *)
        # Unknown option/argument (like help)
        ;;
    esac
done

if [ -z "$COMMAND" ]; then
    echo "Usage: ./run.sh [app|worker] [--skip-ml]"
    echo ""
    echo "Commands:"
    echo "  app         Run the FastAPI web application (Uvicorn server)"
    echo "  worker      Run the background worker runner daemon"
    echo ""
    echo "Flags:"
    echo "  --skip-ml   Run with SKIP_ML=True to skip machine learning inference processing"
    echo ""
    echo "Examples:"
    echo "  ./run.sh app"
    echo "  ./run.sh worker --skip-ml"
    exit 1
fi

# Export SKIP_ML environment variable
export SKIP_ML=$SKIP_ML_VAL

# Ensure the local virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Error: Virtual environment '.venv' not found. Please set up the environment first."
    exit 1
fi

if [ "$COMMAND" = "app" ]; then
    echo "🚀 Starting FastAPI Web App (with SKIP_ML=$SKIP_ML)..."
    .venv/bin/uvicorn app.main:app --reload
elif [ "$COMMAND" = "worker" ]; then
    echo "⚙️ Starting Worker Runner Daemon (with SKIP_ML=$SKIP_ML)..."
    .venv/bin/python -m app.worker_runner
fi
