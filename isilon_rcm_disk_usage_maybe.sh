#!/bin/bash
. /etc/profile.d/modules.sh
module load shared
module load slurm

export PREFIX=/ifs/sysadmin
export PATH=/usr/local/bin:${PREFIX}/bin:${PATH}

echo "$( date -Iminutes ) isilon_rcm_disk_usage_maybe.py starting ..."
python3.9 ${PREFIX}/bin/isilon_rcm_disk_usage_maybe.py
echo "$( date -Iminutes ) isilon_rcm_disk_usage_maybe.py DONE"

