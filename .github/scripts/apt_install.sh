#!/bin/sh
# Install Ubuntu packages on a CI runner: apt_install.sh [APT-GET OPTIONS] PACKAGE...
#
# An install takes under a minute, but some runners draw an Azure mirror crawling at about a package a second, and the
# job then sits until its time limit, which GitHub reports as cancelled. So the mirror the runner came with gets a short
# limit, and Ubuntu's own archive gets the next try. APT_FIRST_LIMIT sets the short limit, in seconds.
set -u

first_limit=${APT_FIRST_LIMIT:-300}

attempt() {
    limit=$1
    shift
    sudo timeout "$limit" sh -c 'apt-get update && apt-get install -y "$@"' apt_install "$@"
}

if attempt "$first_limit" "$@"; then
    exit 0
fi
echo "::warning::apt did not finish on this runner's mirror within $first_limit s; trying archive.ubuntu.com"
sudo dpkg --configure -a
grep -rlI 'azure\.archive\.ubuntu\.com' /etc/apt | xargs -r sudo sed -i 's/azure\.archive\.ubuntu\.com/archive.ubuntu.com/g'
attempt 600 "$@"
