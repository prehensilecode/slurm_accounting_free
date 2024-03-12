#!/bin/bash
. /etc/profile.d/modules.sh
module load shared
module load slurm

export PREFIX=/ifs/sysadmin
export PATH=/usr/local/bin:${PREFIX}/bin:${PATH}

echo "$( date -Iminutes ) update_grptresmins.py STARTING ..."
python3.9 /ifs/sysadmin/bin/update_grptresmins.py
echo "$( date -Iminutes ) update_grptresmins.py DONE"

