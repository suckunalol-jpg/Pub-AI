#!/usr/bin/env python3
"""Quick launcher: python pub-ai.py"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.dirname(__file__))

from cli.app import main
main()
