#!/bin/bash
. /etc/profile.d/modules.sh
module load slurm

export PREFIX=/ifs/sysadmin
export PATH=/usr/local/bin:${PREFIX}/bin:${PATH}

/usr/local/bin/python3.9 ${PREFIX}/bin/generate_monthly_sreports.py

