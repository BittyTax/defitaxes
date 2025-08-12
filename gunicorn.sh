#!/bin/sh

source ./.venv/bin/activate
gunicorn -w 4 -b unix:/tmp/gunicorn.sock --access-logfile - --error-logfile - --preload wsgi:application
