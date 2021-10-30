#!/bin/sh
#disable the update button on the website by doing "touch disable_update" for safety on development signs otherwise uncommitted changes will be wiped on update

#Usage:
#give this file permissions with chmod 777 update.sh
#need to save creds one time after executing:
#git config credential.helper store
#then manually update once and enter credentials manually (these will then be saved to disk... I think)

#TODO:
#-detect if credentials exist and push prompt to website if they don't
#-detect if updating is needed before attempting and/or only show update button on website if there is an update available
#like error checking or something in case the commands don't work idk lol

#can check if an update is needed with:
#[ $(git rev-parse HEAD) = $(git ls-remote $(git rev-parse --abbrev-ref @{u} | \
#sed 's/\// /g') | cut -f1) ] && echo up to date || echo not up to date

if [ -f "disable_update" ]; then
    echo "Update blocked by file: disable_update"
else
    echo "Updating..."

    sudo apt install libatlas-base-dev
    sudo -H pip3 install pytz flask flask_cors numpy scipy yfinance favicon websocket-client
    git fetch
    git reset --hard HEAD
    git pull

    touch sign.conf
    touch prices.csv
    sudo chmod 777 sign.conf
    sudo chmod 777 prices.csv
    sudo chmod -R 777 icons/

    echo "Finished... Rebooting"

    sudo reboot
fi
