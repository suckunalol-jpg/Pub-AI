"""Entry point: python -m cli"""
import sys
import os

# Add backend to path so we can import agent_engine, ai, config, etc.
_backend_dir = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(_backend_dir))

from cli.app import main

if __name__ == "__main__":
    main()
