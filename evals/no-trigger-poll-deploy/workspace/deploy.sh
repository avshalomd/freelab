#!/usr/bin/env bash
rsync -a dist/ deploy@example.invalid:/var/www/landing/
