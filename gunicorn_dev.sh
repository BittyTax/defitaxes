#!/bin/sh

source ./.venv/bin/activate
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export DEV_USER=testuser
gunicorn -t 300 -w 4 --access-logfile - --error-logfile - --preload wsgi:application
