#!/bin/sh

source ./.venv/bin/activate
gunicorn -w 4 -b unix:/tmp/gunicorn.sock -t 300 --access-logfile - --error-logfile - wsgi:app
