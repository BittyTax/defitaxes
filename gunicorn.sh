#!/bin/sh

source ./.venv/bin/activate
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
gunicorn -w 4 -b unix:/tmp/gunicorn.sock --access-logfile - --error-logfile - --preload wsgi:application
