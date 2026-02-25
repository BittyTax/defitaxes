#!/bin/sh

source ./.venv/bin/activate
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
gunicorn -t 300 -w 4 -b unix:/tmp/gunicorn-defi.sock --access-logfile instance/logs/gunicorn/access.log --error-logfile instance/logs/gunicorn/error.log --preload wsgi:application
