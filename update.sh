#!/bin/sh
#echo Updating...
#git checkout
#echo Done
#[ $(git rev-parse HEAD) = $(git ls-remote $(git rev-parse --abbrev-ref @{u} | \
#sed 's/\// /g') | cut -f1) ] && echo up to date || echo not up to date
#
sudo -H pip3 install pytz flask flask_cors libatlas-base-dev numpy scipy yfinance favicon websocket-client
git fetch
git checkout
git reset --hard HEAD

#need to save creds with:
#git -c credential.helper='!f() { echo "username=${uname}"; echo "password=${passwd}"; }; f'