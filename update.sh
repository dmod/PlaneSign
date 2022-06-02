#!/bin/sh
#disable the update button on the website by doing "touch disable_update" for safety on development signs otherwise uncommitted changes will be wiped on update

#Usage:
#give this file permissions with chmod 777 update.sh
#need to save creds one time after executing:
#git config --global credential.helper 'store --file ~/.my-credentials'
#git config --global credential.helper store
#then manually run 'git fetch' and enter credentials manually (these will then be saved to disk)

#TODO:
#-Need more robust way to handle sudo -H pip3 install -r requirements.txt when pip fails on specific a package version
#-detect if credentials exist and push prompt to website if they don't
#-detect if updating is needed before attempting and/or only show update button on website if there is an update available

#can check if an update is needed with:
#[ $(git rev-parse HEAD) = $(git ls-remote $(git rev-parse --abbrev-ref @{u} | \
#sed 's/\// /g') | cut -f1) ] && echo up to date || echo not up to date

if [ -f "disable_update" ]; then
    echo "Update blocked by file: disable_update"
else
    echo "Updating..."

    git fetch
    git reset --hard HEAD
    git pull

    sudo apt install libatlas-base-dev
    sudo -H pip3 install -r requirements.txt

    sudo ./update_static_cache.py

    touch sign.conf
    touch prices.csv

    echo "Finished... Rebooting"

    sudo reboot
fi
